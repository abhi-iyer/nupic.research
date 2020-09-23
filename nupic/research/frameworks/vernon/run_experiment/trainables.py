#  Numenta Platform for Intelligent Computing (NuPIC)
#  Copyright (C) 2019, Numenta, Inc.  Unless you have an agreement
#  with Numenta, Inc., for a separate license for this software code, the
#  following terms and conditions apply:
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero Public License version 3 as
#  published by the Free Software Foundation.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#  See the GNU Affero Public License for more details.
#
#  You should have received a copy of the GNU Affero Public License
#  along with this program.  If not, see http://www.gnu.org/licenses.
#
#  http://numenta.org/licenses/
#

import abc
import copy
import logging
import os
import pickle
import time
from pprint import pformat, pprint

import ray
import ray.resource_spec
import ray.util.sgd.utils as ray_utils
from ray.exceptions import RayActorError
from ray.tune import Trainable
from ray.tune.resources import Resources
from ray.tune.result import DONE, RESULT_DUPLICATE
from ray.tune.utils import warn_if_slow

from nupic.research.frameworks.sigopt import SigOptExperiment

os.environ["HDF5_USE_FILE_LOCKING"] = "FALSE"


class BaseTrainable(Trainable, metaclass=abc.ABCMeta):
    """
    Trainable class used to train arbitrary experiments with ray. Whatever
    the case, it's expected to proceed over well-defined iterations. Thus,
    `_run_iteration` must be overridden.
    """

    @classmethod
    def default_resource_request(cls, config):
        """
        Configure the cluster resources used by this experiment
        """
        num_gpus = config.get("num_gpus", 0)
        num_cpus = config.get("num_cpus", 1)

        if num_gpus > 0:
            # Assign extra CPUs for dataloaders
            workers = config.get("workers", 0)
            num_cpus = workers * num_gpus

        resource = Resources(cpu=0, gpu=0, extra_cpu=num_cpus, extra_gpu=num_gpus)
        return resource

    def _setup(self, config):
        self.experiment_class = config["experiment_class"]

        config["logdir"] = self.logdir

        # Configure logging related stuff
        log_format = config.get("log_format", logging.BASIC_FORMAT)
        log_level = getattr(logging, config.get("log_level", "INFO").upper())
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(log_format))
        self.logger = logging.getLogger(config.get("name", type(self).__name__))
        self.logger.setLevel(log_level)
        self.logger.addHandler(console)

        self.logger.debug(
            f"_setup: trial={self._trial_info.trial_name}({self.iteration}), "
            f"config={config}")

        # Get checkpoint file to restore the training from
        self.restore_checkpoint_file = config.pop("restore_checkpoint_file", None)

        # Try to recover a trial at least this many times
        self.max_retries = max(config.get("max_retries", 3), 0)

        # Create ray remote workers
        self._create_workers(config)

        # Load initial state from checkpoint file
        self._restored = False
        if self.restore_checkpoint_file is not None:
            with open(self.restore_checkpoint_file, mode="rb") as f:
                state = pickle.load(f)
                self._restore(state)
                self._restored = True

        elif config.get("checkpoint_at_init", False):
            # Save initialized model
            self.save()

        self._first_run = True

    def _train(self):
        self.logger.debug(f"_train: {self._trial_info.trial_name}({self.iteration})")
        try:
            # Check if restore checkpoint file fulfills the stop criteria on first run
            pre_experiment_result = None
            if self._first_run:
                self._first_run = False
                if self._restored and self._should_stop():
                    self.logger.warning(
                        f"Restored checkpoint file '{self.restore_checkpoint_file}' "
                        f"fulfills stop criteria without additional training.")
                    return {
                        # Do not train or log results, just stop
                        RESULT_DUPLICATE: True,
                        DONE: True
                    }

                # Run any pre-experiment functionality such as pre-training validation.
                # The results are aggregated here so they may be immediately logged
                # as opposed to waiting till the end of the iteration.
                if self._iteration == 0:
                    status = []
                    for w in self.procs:
                        status.append(w.pre_experiment.remote())

                    agg_pre_exp = self.experiment_class.aggregate_pre_experiment_results
                    if ray_utils.check_for_failure(status):
                        results = ray.get(status)
                        pre_experiment_result = agg_pre_exp(results)
                        self.logger.info(
                            f"Pre-Experiment Result: {pre_experiment_result}"
                        )

            results = self._run_iteration()

            # Aggregate the results from all processes
            if results is not None:

                # Aggregate results from iteration.
                ret = self.experiment_class.aggregate_results(results)

                self._process_result(ret, pre_experiment_result)
                printable_result = self.experiment_class.get_printable_result(ret)
                self.logger.info(f"End Iteration Result: {printable_result}")

                # Check if we should stop the experiment
                ret[DONE] = self._should_stop()

                return ret

            err_msg = (f"{self._trial_info.trial_name}({self.iteration}): "
                       f"One of the remote workers failed during training")
            self.logger.error(err_msg)
            raise RuntimeError(err_msg)
        except Exception:
            self._kill_workers()
            raise

    def _should_stop(self):
        """
        Whether or not we should stop the experiment
        """
        # Check if we should stop the experiment
        stop_status = self.procs[0].should_stop.remote()
        if ray_utils.check_for_failure([stop_status]):
            return ray.get(stop_status)
        else:
            # Stop on failures
            return True

    def _save(self, _=None):
        self.logger.debug(f"_save: {self._trial_info.trial_name}({self.iteration})")
        # All models are synchronized. Just save the state of first model
        with warn_if_slow("ImagenetExperiment.get_state.remote"):
            return ray.get(self.procs[0].get_state.remote())

    def _restore(self, state):
        # Restore the state to every process
        state_id = ray.put(state)
        ray.get([w.set_state.remote(state_id) for w in self.procs])

        # Update current iteration using experiment epoch
        self._iteration = ray.get(self.procs[0].get_current_epoch.remote())

        self.logger.debug(f"_restore: {self._trial_info.trial_name}({self.iteration})")

    def _create_workers(self, config):
        """
        Create one ray remote process for each GPU/process
        """
        num_gpus = config.get("num_gpus", 0)
        num_cpus = config.get("num_cpus", 1)

        # Determine the number of distributed processes based on the number
        # GPUs and CPUs
        if num_gpus > 0:
            world_size = num_gpus
            # Assign one GPU per remote process
            num_gpus = 1
            # Assign extra CPUs for dataloaders
            num_cpus = config.get("workers", 0)
        else:
            world_size = num_cpus
            # Assign one CPU per remote process
            num_cpus = 1

        self._process_config(config)

        for i in range(1 + self.max_retries):
            self.procs = []
            for _ in range(world_size):
                experiment = ray.remote(
                    num_cpus=num_cpus, num_gpus=num_gpus)(self.experiment_class)
                self.procs.append(experiment.remote())

            # Use first process as head of the group
            ip = ray.get(self.procs[0].get_node_ip.remote())
            port = ray.get(self.procs[0].get_free_port.remote())
            port = config.get("dist_port", port)
            dist_url = "tcp://{}:{}".format(ip, port)

            # Configure each process in the group
            status = []
            for rank, w in enumerate(self.procs):
                worker_config = copy.deepcopy(config)
                worker_config["distributed"] = True
                worker_config["dist_url"] = dist_url
                worker_config["world_size"] = world_size
                worker_config["rank"] = rank
                status.append(w.setup_experiment.remote(worker_config))
                self.logger.debug(
                    f"_create_workers: rank={rank}, "
                    f"trial={self._trial_info.trial_name}({self.iteration})")

            # Wait for remote function and check for errors
            if ray_utils.check_for_failure(status):
                return

            # Remote function failed, kill workers and try again
            self.logger.warning(f"Failed to create workers, "
                                f"retrying {i + 1}/{self.max_retries}")
            # Restart all workers on failure
            self._kill_workers()

            # Back off a few seconds
            time.sleep(2 ** i)
        else:
            # Reached max failures
            err_msg = f"Failed to create workers after {self.max_retries} retries"
            self.logger.error(err_msg)
            raise RuntimeError(err_msg)

    def _kill_workers(self):
        for w in self.procs:
            self.logger.warning(
                f"Killing worker {w}, "
                f"trial={self._trial_info.trial_name}({self.iteration})")
            ray.kill(w)
        self.procs = []

    def _stop(self):
        self.logger.debug(f"_stop: {self._trial_info.trial_name}({self.iteration})")
        try:
            status = [w.stop_experiment.remote() for w in self.procs]
            # Wait until all remote workers stop
            ray.get(status)
            for w in self.procs:
                w.__ray_terminate__.remote()
            self.procs = []
        except RayActorError as ex:
            self.logger.warning("Failed to shutdown gracefully", exc_info=ex)
            self._kill_workers()

    def _process_config(self, config):
        pass

    @abc.abstractmethod
    def _run_iteration(self):
        """Run one iteration of the experiment"""
        raise NotImplementedError

    def _process_result(self, result, pre_experiment_result=None):
        pass


class SupervisedTrainable(BaseTrainable):
    """
    Trainable class used to train supervised machine learning experiments
    with ray.
    """

    def _run_iteration(self):
        """Run one epoch of training on each process."""
        status = []
        for w in self.procs:
            status.append(w.run_epoch.remote())

        # Wait for remote functions and check for errors
        if ray_utils.check_for_failure(status):
            return ray.get(status)

    def _process_result(self, result, pre_experiment_result=None):

        # Aggregate initial validation results (before any training).
        if pre_experiment_result is not None:
            result["extra_val_results"].insert(0, (0, pre_experiment_result))


class ContinualLearningTrainable(SupervisedTrainable):
    """
    Trainable class used to train supervised machine learning experiments
    with ray.
    """

    # This is used in the run_with_raytune function to clarify the stopping condition.
    stop_condition = "num_tasks"

    def _run_iteration(self):
        """Run one epoch of training on each process."""
        status = []
        for w in self.procs:
            status.append(w.run_task.remote())

        # Wait for remote functions and check for errors
        if ray_utils.check_for_failure(status):
            return ray.get(status)


class SigOptSupervisedTrainable(SupervisedTrainable):
    """
    This class updates the config using SigOpt before the models and workers are
    instantiated, and updates the result using SigOpt once training completes.
    """

    def _process_config(self, config):
        """
        :param config:
            Dictionary configuration of the trainable

            - sigopt_experiment_id: id of experiment
            - sigopt_config: dict to specify configuration of sigopt experiment
            - sigopt_experiment_class: class inherited from `SigoptExperiment` which
                                       characterizes how the trainable will get and
                                       utilize suggestions

        """
        # Update the config through SigOpt.
        self.sigopt = None
        if "sigopt_config" in config:
            assert config.get("sigopt_experiment_id", None) is not None

            # Check for user specified sigopt-experiment class.
            experiment_class = config.get(
                "sigopt_experiment_class", SigOptExperiment)
            assert issubclass(experiment_class, SigOptExperiment)

            # Instantiate experiment.
            self.sigopt = experiment_class(
                experiment_id=config["sigopt_experiment_id"],
                sigopt_config=config["sigopt_config"])

            self.logger.info(
                f"Sigopt execution order: {pformat(self.sigopt.get_execution_order())}")

            # Get suggestion and update config.
            self.suggestion = self.sigopt.get_next_suggestion()
            self.sigopt.update_config_with_suggestion(config, self.suggestion)
            print("SigOpt suggestion: ", self.suggestion)
            print("Config after Sigopt:")
            pprint(config)
            self.epochs = config["epochs"]

            # Get names of performance metrics.
            assert "metrics" in config["sigopt_config"]
            self.metric_names = [
                metric["name"] for metric in config["sigopt_config"]["metrics"]
            ]
            assert "mean_accuracy" in self.metric_names, \
                "For now, we only update the observation if `mean_accuracy` is present."

    def _process_result(self, result, pre_experiment_result=None):
        """
        Update sigopt with the new result once we're at the end of training.
        """

        super()._process_result(result, pre_experiment_result=pre_experiment_result)

        if self.sigopt is not None:
            result["early_stop"] = result.get("early_stop", 0.0)
            if self.iteration >= self.epochs - 1:
                result["early_stop"] = 1.0
                if result["mean_accuracy"] > 0.0:
                    print("Updating observation with value=", result["mean_accuracy"])

                    # Collect and report relevant metrics.
                    values = [
                        dict(name=name, value=result[name])
                        for name in self.metric_names
                    ]
                    self.sigopt.update_observation(self.suggestion, values=values)
                    print("Full results: ")
                    pprint(result)


class DebugTrainable(Trainable):
    """Simple trainable compatible with experiment class and config. For debugging."""

    def __init__(self, config=None, logger_creator=None):
        Trainable.__init__(self, config=config, logger_creator=logger_creator)

    def _setup(self, config):
        self.experiment_class = config.get("experiment_class")
        self.experiment = self.experiment_class()
        self.experiment.setup_experiment(config)

    def _train(self):
        ret = self.experiment.run_task()
        printable_result = self.experiment_class.get_printable_result(ret)
        print(f"End Iteration Result: {printable_result}")

        return ret

    def _save(self, checkpoint_dir):
        return dict()

    def _restore(self, checkpoint):
        pass
