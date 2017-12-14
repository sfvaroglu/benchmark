"""VGG16 benchmark"""
from __future__ import print_function

import sys
import time
import numpy as np
import paddle.v2 as paddle
import paddle.v2.fluid as fluid
import argparse
import functools

parser = argparse.ArgumentParser("VGG16 benchmark.")
parser.add_argument(
    '--batch_size', type=int, default=32, help="Batch size for training.")
parser.add_argument(
    '--learning_rate',
    type=float,
    default=1e-3,
    help="Learning rate for training.")
parser.add_argument('--num_passes', type=int, default=10, help="No. of passes.")
parser.add_argument(
    '--device',
    type=str,
    default='CPU',
    choices=['CPU', 'GPU'],
    help="The device type.")
parser.add_argument(
    '--data_format',
    type=str,
    default='NHWC',
    choices=['NCHW', 'NHWC'],
    help='The data order, now only support NCHW.')
parser.add_argument(
    '--num_skip_batch',
    type=int,
    default=0,
    help='The first #num_skip_batch batches'
    'will be skipped for timing.')
parser.add_argument(
    '--iterations', type=int, default=10, help='Maximum iterations')
args = parser.parse_args()


def vgg16_bn_drop(input):
    def conv_block(input, num_filter, groups, dropouts):
        return fluid.nets.img_conv_group(
            input=input,
            pool_size=2,
            pool_stride=2,
            conv_num_filter=[num_filter] * groups,
            conv_filter_size=3,
            conv_act='relu',
            conv_with_batchnorm=True,
            conv_batchnorm_drop_rate=dropouts,
            pool_type='max')

    conv1 = conv_block(input, 64, 2, [0.3, 0])
    conv2 = conv_block(conv1, 128, 2, [0.4, 0])
    conv3 = conv_block(conv2, 256, 3, [0.4, 0.4, 0])
    conv4 = conv_block(conv3, 512, 3, [0.4, 0.4, 0])
    conv5 = conv_block(conv4, 512, 3, [0.4, 0.4, 0])

    drop = fluid.layers.dropout(x=conv5, dropout_prob=0.5)
    fc1 = fluid.layers.fc(input=drop, size=512, act=None)
    bn = fluid.layers.batch_norm(input=fc1, act='relu')
    drop2 = fluid.layers.dropout(x=bn, dropout_prob=0.5)
    fc2 = fluid.layers.fc(input=drop2, size=102, act=None)
    return fc2


def main():
    classdim = 102
    data_shape = [3, 224, 224]

    images = fluid.layers.data(name='pixel', shape=data_shape, dtype='float32')
    label = fluid.layers.data(name='label', shape=[1], dtype='int64')

    net = vgg16_bn_drop(images)
    predict = fluid.layers.fc(input=net, size=classdim, act='softmax')
    cost = fluid.layers.cross_entropy(input=predict, label=label)
    avg_cost = fluid.layers.mean(x=cost)

    optimizer = fluid.optimizer.Adam(learning_rate=args.learning_rate)
    opts = optimizer.minimize(avg_cost)

    accuracy = fluid.evaluator.Accuracy(input=predict, label=label)

    train_reader = paddle.batch(
        paddle.reader.shuffle(
            paddle.dataset.flowers.train(), buf_size=5120),
        batch_size=args.batch_size)

    place = fluid.CPUPlace() if args.device == 'CPU' else fluid.GPUPlace(0)
    exe = fluid.Executor(place)

    exe.run(fluid.default_startup_program())

    iters, num_samples, start_time = 0, 0, 0.0
    for pass_id in range(args.num_passes):
        if args.iterations == iters:
            break
        accuracy.reset(exe)
        pass_begin = time.clock()
        for batch_id, data in enumerate(train_reader()):
            batch_begin = time.clock()
            if args.num_skip_batch == iters:
                start_time = time.clock()
            img_data = np.array(map(lambda x: x[0].reshape(data_shape),
                                    data)).astype("float32")
            y_data = np.array(map(lambda x: x[1], data)).astype("int64")
            batch_size = 1
            for i in y_data.shape:
                batch_size = batch_size * i
            y_data = y_data.reshape([batch_size, 1])

            loss, acc = exe.run(fluid.default_main_program(),
                                feed={"pixel": img_data,
                                      "label": y_data},
                                fetch_list=[avg_cost] + accuracy.metrics)
            batch_end = time.clock()
            print("pass=%d, batch=%d, loss=%f, acc=%f, time=%f" %
                  (pass_id, batch_id, loss, acc, batch_end - batch_begin))
            iters += 1
            if iters > args.num_skip_batch:
                num_samples += len(data)
            if args.iterations == iters:
                break
        pass_acc = accuracy.eval(exe)
        pass_end = time.clock()
        print("pass %d, training_acc=%f, elapsed_time=%fs\n" %
              (pass_id, pass_acc, (pass_end - pass_begin)))

    duration = time.clock() - start_time
    imgs_per_sec = num_samples / duration
    print("duration=%fs, performance=%fimgs/s" % (duration, imgs_per_sec))


def print_arguments():
    print('-----------  Configuration Arguments -----------')
    for arg, value in sorted(vars(args).iteritems()):
        print('%s: %s' % (arg, value))
    print('------------------------------------------------')


if __name__ == "__main__":
    print_arguments()
    main()
