import time, timeit
from time import perf_counter
from functools import partial

import jax
import optax
import jax.numpy as jnp


# ctc loss
@partial(jax.jit, static_argnums=(2,))
def ctc_loss(logits, targets, blank_id=0, **kwargs):
    logits_padding = jnp.zeros(logits.shape[:2])
    labels_padding = jnp.where(targets == blank_id, 1, 0)
    return optax.ctc_loss(
        logits=logits,
        labels=targets,
        logit_paddings=logits_padding,
        label_paddings=labels_padding,
    )


@partial(jax.jit, static_argnums=(2, 3, 4))
def focal_ctc_loss(logits, targets, blank_id=0, alpha=0.25, gamma=2, **kwargs):
    loss = ctc_loss(logits, targets, blank_id)
    focal = alpha * jnp.power(1 - jnp.exp(-loss), gamma) * loss
    return focal.mean()


def focal_ctc_loss_test():
    labels = jnp.array([
        #0,1,2,3,4,5,6,7,8,9,A,B,C,D,E,F
        [6,2,1,1,7,7,5,8,0,0,0,0,0,0,0],
        [9,0,4,0,1,0,2,0,4,0,8,0,9,0,8],
        [9,0,4,0,2,0,2,0,4,0,8,0,9,0,8],
    ])
    key = jax.random.PRNGKey(0)
    n, t, c = labels.shape[0], labels.shape[1], 10
    logits = jax.random.normal(key, (n, t, c))
    loss = 0
    # timeit and get function result
    start_t = perf_counter()
    for i in range(1000):
        loss = focal_ctc_loss(logits, labels, alpha=0.25, gamma=3)
    end_t = perf_counter()
    avg_time = (end_t - start_t) / 1000
    print('\33[92m[pass]\33[00m focal_ctc_loss() test passed.')
    print('  - loss:', loss)
    print('  - time: {:.6f} ms'.format(avg_time*1000))


# dice bce loss via optax
@jax.jit
def dice_bce_loss(logits, targets, smooth=1e-7, **kwargs):
    # logits: (B, H, W, C), get from logits without sigmoid
    # targets: (B, H, W, C)
    # smooth: (float) smooth value
    # return: (B,)

    # sigmod it if the model doesn't have sigmoid activation
    _logits = jax.nn.sigmoid(logits)

    # dice loss
    pred = _logits.flatten()
    true = targets.flatten()
    intersection = jnp.sum(pred * true)
    union = jnp.sum(pred) + jnp.sum(true)
    dice = 1 - (2 * intersection + smooth) / (union + smooth)

    # bce loss
    bce = optax.sigmoid_binary_cross_entropy(logits, targets).mean()
    return bce + dice


def dice_bce_test():
    # test dice bce loss
    logits = jnp.zeros((1, 10, 10, 3))
    logits = logits.at[:, 2:4, 2:4, 0].set(1)
    logits = logits.at[:, 4:6, 4:6, 1].set(1)
    targets = jnp.zeros((1, 10, 10, 3))
    targets = targets.at[:, 2:4, 2:4, 0].set(1)
    targets = targets.at[:, 4:6, 4:6, 1].set(1)

    # get raw logits before sigmoid
    logits = jnp.clip(logits, 1e-7, 1 - 1e-7)
    logits = jnp.log(logits / (1 - logits))

    start_t = perf_counter()
    for i in range(1000):
        loss = dice_bce_loss(logits, targets)
    end_t = perf_counter()

    avg_time = (end_t - start_t) / 1000
    print('\33[92m[pass]\33[00m dice_bce_loss() test passed.')
    print('  - loss:', loss)
    print('  - time: {:.6f} ms'.format(avg_time*1000))


@partial(jax.jit, static_argnums=(1, 2))
def center_ctc_loss(logits, n_class=10, n_feat=64, **kwargs):
    feats, preds = logits
    classes = jnp.arange(n_class)
    centers = jnp.zeros((n_class, n_feat))

    feats_reshape = feats.reshape(-1, n_feat)
    batch_size = feats_reshape.shape[0]

    feat = jnp.sum(jnp.square(feats_reshape), axis=1, keepdims=True)
    feat = jnp.broadcast_to(feat, (batch_size, n_class))

    center = jnp.sum(jnp.square(centers), axis=1, keepdims=True)
    center = jnp.broadcast_to(center, (n_class, batch_size))

    distmat = feat + center.T
    feat_dot_center = jnp.matmul(feats_reshape, centers.T)
    distmat = distmat - 2.0 * feat_dot_center

    preds = jax.nn.log_softmax(preds)
    labels = preds.argmax(axis=-1).reshape(-1)
    labels = jnp.broadcast_to(jnp.expand_dims(labels, axis=1), (batch_size, n_class))
    mask = jnp.equal(
        jnp.broadcast_to(classes, (batch_size, n_class)),
        labels,
    )

    dist = distmat * mask
    dist = jnp.clip(dist, a_min=1e-12, a_max=1e+12)
    return jnp.sum(dist) / batch_size


def center_ctc_loss_test():
    # shape: (N, T, features), (N, T, classes)
    feats = jnp.zeros((1, 10, 64))
    preds = jnp.zeros((1, 10, 10))
    logits = (feats, preds)
    start_t = perf_counter()
    for i in range(1000):
        loss = center_ctc_loss(logits)
    end_t = perf_counter()
    assert loss < 1e-10 # loss should be close to zero
    avg_time = (end_t - start_t) / 1000
    print('\33[92m[pass]\33[00m center_ctc_loss() test passed.')
    print('  - loss:', loss)
    print('  - time: {:.6f} ms'.format(avg_time*1000))


@jax.jit
def ce_ctc_loss(logits, labels):
    # logits: (B, T, C)
    # labels: (B, T)
    # return: (B,)

    # using ce loss
    bs, t, n_class = logits.shape
    # one-hot
    labels = jax.nn.one_hot(labels, n_class)
    loss = optax.softmax_cross_entropy(logits, labels).mean()
    return loss


if __name__ == "__main__":
    # cpu mode
    jax.config.update('jax_platform_name', 'cpu')
    print(jax.devices())

    dice_bce_test()
    focal_ctc_loss_test()
    center_ctc_loss_test()
