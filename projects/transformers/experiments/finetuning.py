#  Numenta Platform for Intelligent Computing (NuPIC)
#  Copyright (C) 2021, Numenta, Inc.  Unless you have an agreement
#  with Numenta, Inc., for a separate license for this software code, the
#  following terms and conditions apply:
#
#  This program is free software you can redistribute it and/or modify
#  it under the terms of the GNU Affero Public License version 3 as
#  published by the Free Software Foundation.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#  See the GNU Affero Public License for more details.
#
#  You should have received a copy of the GNU Affero Public License
#  along with this program.  If not, see htt"://www.gnu.org/licenses.
#
#  http://numenta.org/licenses/
#

"""
Base Transformers Experiment configuration.
"""

from copy import deepcopy

from transformers import EarlyStoppingCallback

from callbacks import TrackEvalMetrics

from .base import transformers_base

"""
Expected for qnli 0.9066 acc, 41 min training time. seed may affect result
Achieved ~0.8896 acc, 11min training time on 4 GPUs.

Effective batch size was 128 with 1/4 the number of steps, so results were expected to
be lower than baseline.

See a summary of the Static Sparse Baseline here:
https://wandb.ai/numenta/huggingface/reports/Static-Sparse-Baselines--Vmlldzo1MTY1MTc
"""

# Runs can easily break because metric_for_best_model varies by task,
# but is required if using early_stopping. So it's easy to specify a metric
# that isn't present for the current task. This is a reference to help avoid that.
#
# "cola": ["eval_matthews_correlation"],
# "mnli": ["eval_accuracy", "mm_eval_accuracy"],
# "mrpc": ["eval_f1", "eval_accuracy"],
# "qnli": ["eval_accuracy"],
# "qqp": ["eval_accuracy", "eval_f1"],
# "rte": ["eval_accuracy"],
# "sst2": ["eval_accuracy"],
# "stsb": ["eval_pearson", "eval_spearmanr"],
# "wnli": ["eval_accuracy"]

debug_finetuning_no_early_stopping = deepcopy(transformers_base)
debug_finetuning_no_early_stopping.update(
    # Data arguments
    task_name="wnli",
    max_seq_length=128,

    # Model arguments
    finetuning=True,
    model_name_or_path="bert-base-cased",

    # Training arguments
    do_train=True,
    do_eval=True,
    do_predict=True,
    eval_steps=10,
    evaluation_strategy="steps",
    load_best_model_at_end=True,
    per_device_train_batch_size=32,
    per_device_eval_batch_size=32,
    learning_rate=2e-5,
    warmup_ratio=0.1,
    max_steps=50,  # made very short for fast debugging
)

debug_finetuning = deepcopy(transformers_base)
debug_finetuning.update(
    # Data arguments
    task_name="mnli",
    max_seq_length=128,

    # Model arguments
    finetuning=True,
    model_name_or_path="bert-base-cased",

    # Training arguments
    do_train=True,
    do_eval=True,
    do_predict=True,
    eval_steps=10,
    evaluation_strategy="steps",
    load_best_model_at_end=True,
    per_device_train_batch_size=32,
    per_device_eval_batch_size=32,
    learning_rate=2e-5,
    warmup_ratio=0.1,
    max_steps=50,  # made very short for fast debugging
    metric_for_best_model="eval_accuracy",
    trainer_callbacks=[
        TrackEvalMetrics(),
        EarlyStoppingCallback(early_stopping_patience=5)
    ],
)


"""
Acc for bert 100k: 0.8641 (in 4 GPUs)
"""
debug_finetuning_bert100k = deepcopy(debug_finetuning)
debug_finetuning_bert100k.update(
    # Data arguments
    overwrite_output_dir=True,

    # Model from checkpoint
    model_name_or_path="/mnt/efs/results/pretrained-models/transformers-local/bert_100k",  # noqa: E501

    # logging
    run_name="debug_finetuning_bert100k",
)

debug_finetuning_bert100k_ntasks = deepcopy(debug_finetuning_bert100k)
debug_finetuning_bert100k_ntasks.update(
    # logging
    report_to="tensorboard",
    task_name="glue",
    run_name="debug_finetuning_bert100k_ntasks",
    # task_name=None,
    # task_names=["cola", "stsb", "mnli"],
    max_steps=300,
    override_finetuning_results=False,
    task_hyperparams=dict(
        wnli=dict(num_runs=2, max_steps=20, learning_rate=2e-4),
        rte=dict(num_runs=1),
        cola=dict(num_runs=2),
        stsb=dict(num_runs=1,
                  metric_for_best_model="pearson"),
    ),
    do_predict=False,
)


finetuning_bert700k_glue = deepcopy(transformers_base)
finetuning_bert700k_glue.update(
    # logging
    overwrite_output_dir=True,
    override_finetuning_results=True,

    # Data arguments
    task_name="glue",
    max_seq_length=128,

    # Model arguments
    finetuning=True,
    model_name_or_path="/mnt/efs/results/pretrained-models/transformers-local/bert_700k",  # noqa: E501
    do_train=True,
    do_eval=True,
    do_predict=False,
    eval_steps=10,
    evaluation_strategy="steps",
    load_best_model_at_end=True,
    per_device_train_batch_size=32,
    per_device_eval_batch_size=32,
    learning_rate=2e-5,
    metric_for_best_model="eval_accuracy",
    num_train_epochs=3,
    num_runs=1,
    task_hyperparams=dict(
        mrpc=dict(num_train_epochs=5, num_runs=3),
        wnli=dict(num_train_epochs=5, num_runs=10),
        cola=dict(num_train_epochs=5, num_runs=10),
        stsb=dict(num_runs=3),
        rte=dict(num_runs=10),
    ),
    trainer_callbacks=[
        TrackEvalMetrics(),
        EarlyStoppingCallback(early_stopping_patience=5)
        ],
)

finetuning_bert100k_glue = deepcopy(finetuning_bert700k_glue)
finetuning_bert100k_glue.update(
    # logging
    overwrite_output_dir=True,
    model_name_or_path="/mnt/efs/results/pretrained-models/transformers-local/bert_100k",  # noqa: E501
)

# The name 'simple' is in reference to the paper "On the stability of finetuning BERT"
# where they propose a "simple but hard to beat" approach
#       https://openreview.net/pdf?id=nzpLWnVAyah
#
# How to training time for each task:
# They recommend 20 epochs for rte, which is about 50k examples. With a batch size
# of 32, thats about 1562 steps. They also claim that the number of examples is
# more important than dataset size. Here I aim for 1562 steps unless the size of
# the training set is already > 50k.
#
#       if len(train_dataset) < 50k
#           train for ~ 50k iterations = round(50k / len(train_dataset))
#           (cola, mrpc, stsb, rte, wnli)
#
#       else
#           use the default of 3 epochs
#
# Note that EarlyStoppingCallback is in use, which was not mentioned in the paper

finetuning_bert100k_glue_simple = deepcopy(finetuning_bert100k_glue)
finetuning_bert100k_glue_simple.update(
    warmup_ratio=0.1,
    trainer_callbacks=[TrackEvalMetrics(), EarlyStoppingCallback()],
    task_hyperparams=dict(
        cola=dict(max_steps=1562, num_runs=5),  # 50k / 8500 ~ 6 epochs
        sst2=dict(num_runs=3),  # 67k training size > 50k, default 3 epochs
        mrpc=dict(max_steps=1562, num_runs=3),  # 50k / 3700 ~ 14 epochs
        stsb=dict(num_train_epochs=8, num_runs=3),  # 50k / 7000 ~ 8 epochs
        qqp=dict(num_runs=3),  # 300k >> 50k
        mnli=dict(num_runs=3),  # 300k >> 50k
        qnli=dict(num_runs=3),  # 100k > 50k, defualt to 3 epochs
        rte=dict(max_steps=1562, num_runs=3),  # ~ 20 epochs from paper
        wnli=dict(max_steps=1562, num_runs=3)  # 50k / 634 ~ 79 epochs
    )
)

finetuning_bert1mi_glue_simple = deepcopy(finetuning_bert100k_glue_simple)
finetuning_bert1mi_glue_simple.update(
    model_name_or_path="/mnt/efs/results/pretrained-models/transformers-local/bert_1mi"
)

finetuning_bert1mi_glue = deepcopy(finetuning_bert700k_glue)
finetuning_bert1mi_glue.update(
    # logging
    overwrite_output_dir=True,
    model_name_or_path="/mnt/efs/results/pretrained-models/transformers-local/bert_1mi",
)

finetuning_bert100k_single_task = deepcopy(finetuning_bert100k_glue)
finetuning_bert100k_single_task.update(
    # logging
    task_name=None,
    task_names=["rte", "wnli", "stsb", "mrpc", "cola"],
)


finetuning_bert1mi_wnli = deepcopy(finetuning_bert100k_single_task)
finetuning_bert1mi_wnli.update(
    # Data arguments
    task_name=None,
    task_names=["wnli"],
    # Training arguments
    evaluation_strategy="steps",
    eval_steps=5,
    load_best_model_at_end=True,
    metric_for_best_model="eval_accuracy",
    max_steps=20,  # make short for quick check if debugging
    num_runs=3,
    trainer_callbacks=[
        TrackEvalMetrics(),
        EarlyStoppingCallback(early_stopping_patience=5)
    ],
)


finetuning_tiny_bert50k_glue = deepcopy(finetuning_bert700k_glue)
finetuning_tiny_bert50k_glue.update(
    model_name_or_path="/home/ec2-user"
                       "/nta/results/experiments/transformers/tiny_bert_50k"
)


finetuning_bert700k_single_task = deepcopy(finetuning_bert700k_glue)
finetuning_bert700k_single_task.update(
    # logging
    task_name=None,
    task_names=["rte", "wnli", "stsb", "mrpc", "cola"],
)

finetuning_bert1mi_single_task = deepcopy(finetuning_bert1mi_glue)
finetuning_bert1mi_single_task.update(
    # logging
    task_name=None,
    task_names=["rte", "wnli", "stsb", "mrpc", "cola"],
    overwrite_output_dir=True,
    model_name_or_path="/mnt/efs/results/pretrained-models/transformers-local/bert_1mi",
)


finetuning_sparse_bert_100k_glue = deepcopy(finetuning_bert700k_glue)
finetuning_sparse_bert_100k_glue.update(
    # Model arguments
    model_type="static_sparse_non_attention_bert",
    model_name_or_path="/mnt/efs/results/pretrained-models/transformers-local/static_sparse_non_attention_bert_100k",  # noqa: E501
)


finetuning_sparse_encoder_bert_100k_glue = deepcopy(finetuning_bert700k_glue)
finetuning_sparse_encoder_bert_100k_glue.update(
    # Model arguments
    model_type="static_sparse_encoder_bert",
    model_name_or_path="/mnt/efs/results/pretrained-models/transformers-local/static_sparse_encoder_bert_100k",  # noqa: E501
)


finetuning_fully_sparse_bert_100k_glue = deepcopy(finetuning_bert700k_glue)
finetuning_fully_sparse_bert_100k_glue.update(
    # Model arguments
    model_type="fully_static_sparse_bert",
    model_name_or_path="/mnt/efs/results/pretrained-models/transformers-local/bert_sparse_80%_100k",  # noqa: E501
)


finetuning_mini_sparse_bert_debug = deepcopy(finetuning_bert700k_glue)
finetuning_mini_sparse_bert_debug.update(
    model_type="static_sparse_encoder_bert",
    model_name_or_path="/home/ec2-user/nta/results/experiments/transformers/mini_sparse_bert_debug",  # noqa: E501
)


# Export configurations in this file
CONFIGS = dict(
    debug_finetuning=debug_finetuning,
    debug_finetuning_no_early_stopping=debug_finetuning_no_early_stopping,
    debug_finetuning_bert100k=debug_finetuning_bert100k,
    debug_finetuning_bert100k_ntasks=debug_finetuning_bert100k_ntasks,
    finetuning_bert100k_glue=finetuning_bert100k_glue,
    finetuning_bert100k_single_task=finetuning_bert100k_single_task,
    finetuning_tiny_bert50k_glue=finetuning_tiny_bert50k_glue,
    finetuning_bert700k_glue=finetuning_bert700k_glue,
    finetuning_bert700k_single_task=finetuning_bert700k_single_task,
    finetuning_bert100k_glue_simple=finetuning_bert100k_glue_simple,
    finetuning_bert1mi_glue=finetuning_bert1mi_glue,
    finetuning_bert1mi_glue_simple=finetuning_bert1mi_glue_simple,
    finetuning_bert1mi_wnli=finetuning_bert1mi_wnli,
    finetuning_bert1mi_single_task=finetuning_bert1mi_single_task,
    finetuning_sparse_bert_100k_glue=finetuning_sparse_bert_100k_glue,
    finetuning_sparse_encoder_bert_100k_glue=finetuning_sparse_encoder_bert_100k_glue,
    finetuning_mini_sparse_bert_debug=finetuning_mini_sparse_bert_debug,
    finetuning_fully_sparse_bert_100k_glue=finetuning_fully_sparse_bert_100k_glue,
)
