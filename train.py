import os, sys, random, time, glob, math
# XLA_PYTHON_CLIENT_MEM_FRACTION=.90
os.environ["XLA_PYTHON_CLIENT_MEM_FRACTION"] = ".90"

import jax
# because of the bug of jax on mac os
if sys.platform == "darwin":
    jax.config.update('jax_platform_name', 'cpu')
print(jax.devices())

import yaml
import optax
import jax.numpy as jnp
import tensorflow_datasets as tfds

sys.path.append("./utils")
from model.loss import *
from model.model import TinyLPR
from model.dataloader import get_data
from utils import batch_ctc_greedy_decoder, batch_remove_blank
from fit import lr_schedule, fit, TrainState, load_ckpt


cfg = yaml.safe_load(open("config.yaml"))
print(cfg)

val_ds, _ = get_data(**cfg["val"])
train_ds, train_len = get_data(**cfg["train"])
train_dl, val_dl = tfds.as_numpy(train_ds), tfds.as_numpy(val_ds)

lr_fn = lr_schedule(cfg["lr"], train_len, cfg["epochs"], cfg["warmup"])


@jax.jit
def train_step(state: TrainState, batch, opt_state):
    img, mask, label = batch
    def loss_fn(params):
        (pred_mask, pred_feat, pred_ctc), updates = state.apply_fn({
            'params': params,
            'batch_stats': state.batch_stats
        }, img, train=True, mutable=['batch_stats'])
        loss_ctc = focal_ctc_loss(pred_ctc, label, **cfg["focal_ctc_loss"])
        loss_mask = dice_bce_loss(pred_mask, mask)
        loss_center = center_ctc_loss((pred_feat, pred_ctc), **cfg["center_ctc_loss"])

        loss_center = jax.lax.cond(
            state.step <= 10300,
            lambda x: jnp.array(.0, dtype=jnp.float32),
            lambda x: loss_center,
            None
        )

        loss = (cfg["focal_ctc_loss"]["weight"] * loss_ctc +
                cfg["dice_bce_loss"]["weight"] * loss_mask +
                cfg["center_ctc_loss"]["weight"] * loss_center)

        loss_dict = {
            'loss': loss,
            'loss_ctc': loss_ctc,
            'loss_mask': loss_mask,
            'loss_center': loss_center,
        }
        return loss, (loss_dict, updates)

    (_, (loss_dict, updates)), grads = jax.value_and_grad(loss_fn, has_aux=True)(state.params)
    state = state.apply_gradients(grads=grads, batch_stats=updates['batch_stats'])
    _, opt_state = state.tx.update(grads, opt_state)
    return state, loss_dict, opt_state


def predict(state: TrainState, batch):
    img, _, label = batch
    pred_ctc = state.apply_fn({
        'params': state.params,
        'batch_stats': state.batch_stats
        }, img, train=False)
    return pred_ctc, label


def eval_step(state: TrainState, batch):
    pred_ctc, label = jax.jit(predict)(state, batch)
    label = batch_remove_blank(label)
    pred = batch_ctc_greedy_decoder(pred_ctc)
    acc = jnp.mean(jnp.array([1 if jnp.array_equal(
        l, p) else 0 for l, p in zip(label, pred)]))
    return state, acc


if __name__ == "__main__":
    key = jax.random.PRNGKey(0)
    x = jnp.zeros((1, *cfg["img_size"], 1))

    model = TinyLPR(**cfg["model"])
    var = model.init(key, x, train=True)
    params = var['params']
    batch_stats = var['batch_stats']

    state = TrainState.create(
        apply_fn=model.apply,
        params=params,
        batch_stats=batch_stats,
        tx=optax.inject_hyperparams(optax.nadam)(lr_fn),
    )

    state = load_ckpt(state, cfg["ckpt"])

    fit(state, train_dl, val_dl,
        train_step=train_step,
        eval_step=eval_step,
        num_epochs=cfg["epochs"],
        eval_freq=cfg["eval_freq"],
        log_name="tiny_lpr",
    )
