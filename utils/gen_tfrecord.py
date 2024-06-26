import os, sys, glob
import yaml

import numpy as np
from PIL import Image, ImageDraw
import tensorflow as tf
import matplotlib.pyplot as plt

sys.path.append("./utils")
from gen_label import *
from utils import load_image


# load config data from config file
cfg = yaml.safe_load(open("config.yaml"))
time_steps = cfg['time_steps']
img_size = cfg['img_size']


def gen_mask(bbox, size, len_label, time_step=time_steps):
    mask = np.zeros((size[0], size[1], time_step), dtype=np.int32)
    h, w = size

    for i, box in enumerate(bbox):
        b0 = max(0, box[0])
        b1 = max(0, box[1])
        b2 = min(w, box[2])
        b3 = min(h, box[3])
        # mask[b1:b3, b0:b2, i] = 1
        mask[b1:b3, b0:b2, time_step-(2*(len_label-i)-1)] = 1

    return mask


# resize image to width=196 and keep aspect ratio, also resize the bboxes(4 points)
# bbox: [x1, y1, x2, y2] and int64
def resize_image_keep_aspect_ratio(image, bbox, width=192):
    h, w, _ = image.shape
    ratio = width / w
    new_h = int(h * ratio)
    image = tf.image.resize(image, (new_h, width), antialias=True)
    bbox = tf.cast(bbox, tf.float32)
    bbox = tf.cast(tf.round(bbox * ratio), tf.int64)
    return image, bbox


def resize_image_and_bbox(image, bbox, size=img_size):
    h, w, _ = image.shape
    r_h = size[0] / h
    r_w = size[1] / w
    image = tf.image.resize(image, size, antialias=True)
    bbox = tf.cast(bbox, tf.float32)
    bbox = tf.cast(tf.round(bbox * [r_w, r_h, r_w, r_h]), tf.int64)
    return image, bbox


def _bytes_feature(value):
    return tf.train.Feature(bytes_list=tf.train.BytesList(value=[value]))


def gen_tfrecord(dir_path, file_name):
    writer = tf.io.TFRecordWriter(
        'data/{}.tfrecord'.format(file_name),
        options=tf.io.TFRecordOptions(compression_type='ZLIB'))

    img_ds = glob.glob(dir_path + '/*.jpg')
    # shuffle the dataset
    # np.random.shuffle(img_ds)

    for img_path in img_ds:
        txt_path = img_path.replace('.jpg', '.txt')
        bbox = np.loadtxt(txt_path, dtype=np.int64)
        _, label = gen_label(img_path)

        image = Image.open(img_path).convert('RGB')
        image, bbox = resize_image_keep_aspect_ratio(np.array(image, dtype=np.float32), bbox)
        # image, bbox = resize_image_and_bbox(np.array(image, dtype=np.float32), bbox)
        height, width, _ = image.shape
        mask = gen_mask(bbox, (height, width), len(label))

        # # sum the mask to one channel
        # mask = np.sum(mask, axis=2)
        # # save the mask as test.png
        # mask = Image.fromarray(np.array(mask, dtype=np.uint8) * 255)
        # mask.save('test.png')

        # # draw box on the image
        # image = Image.fromarray(np.array(image, dtype=np.uint8))
        # draw = ImageDraw.Draw(image)

        # for box in bbox:
        #     draw.rectangle([box[0], box[1], box[2], box[3]], outline='red')

        # # img.show()
        # # save the image
        # image.save('test.jpg')
        # quit()

        image = np.array(image, dtype=np.uint8).tobytes()
        mask = np.array(mask, dtype=np.int64).tobytes()
        label = np.array(label, dtype=np.int64).tobytes()

        size = np.array([height, width], dtype=np.int64).tobytes()

        feature = {
            'image': _bytes_feature(image),
            'mask': _bytes_feature(mask),
            'label': _bytes_feature(label),
            'size': _bytes_feature(size),
        }

        writer.write(tf.train.Example(features=tf.train.Features(
            feature=feature)).SerializeToString())

    writer.close()
    print("\033[1;32m{} tfrecord done\033[0m".format(file_name))


if __name__ == '__main__':
    val_path = '/Users/haoyu/Documents/datasets/lpr/val'
    train_path = '/Users/haoyu/Documents/datasets/lpr/train'

    gen_tfrecord(val_path, 'val')
    gen_tfrecord(train_path, 'train')
    print('done')
