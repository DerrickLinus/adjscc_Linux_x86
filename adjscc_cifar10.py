from util_channel import Channel
from util_module import Attention_Encoder, Attention_Decoder
from tensorflow.keras.layers import Input, Lambda
from tensorflow.keras import Model
from tensorflow.keras.optimizers import Adam
import tensorflow as tf
import numpy as np
import argparse
from dataset import dataset_cifar10
import os
import json

AUTOTUNE = tf.data.experimental.AUTOTUNE


def train(args, model):
    epoch_list = []
    loss_list = []
    val_loss_list = []
    min_loss = 10 ** 8
    filename = os.path.basename(__file__).split('.')[0] + '_' + str(args.channel_type) + '_tcn' + str(
        args.transmit_channel_num) + '_snrdb' + str(args.snr_low_train) + 'to' + str(
        args.snr_up_train) + '_bs' + str(args.batch_size) + '_lr' + str(args.learning_rate)
    model_path = args.model_dir + filename + '.h5'
    # 检查并创建 model 目录（如果不存在）
    if args.model_dir and not os.path.exists(args.model_dir):
        os.makedirs(args.model_dir, exist_ok=True)
        print(f"Directory {args.model_dir} created.")
    if args.load_model_path != None: 
        model.load_weights(args.load_model_path) 
    for epoch in range(0, args.epochs):
        if args.channel_type == 'awgn':
            (train_ds, train_nums), (test_ds, test_nums) = dataset_cifar10.get_dataset_snr_range(args.snr_low_train,
                                                                                                 args.snr_up_train)
        elif args.channel_type == 'slow_fading' or args.channel_type == 'slow_fading_eq':
            (train_ds, train_nums), (test_ds, test_nums) = dataset_cifar10.get_dataset_snr_range_and_h(
                args.snr_low_train, args.snr_up_train)
        train_ds = train_ds.shuffle(buffer_size=train_nums)
        train_ds = train_ds.batch(args.batch_size)
        test_ds = test_ds.shuffle(buffer_size=test_nums)
        test_ds = test_ds.batch(args.batch_size)
        train_ds = train_ds.prefetch(buffer_size=AUTOTUNE)
        h = model.fit(train_ds, epochs=1, steps_per_epoch=(
            train_nums // args.batch_size if train_nums % args.batch_size == 0 else train_nums // args.batch_size + 1),
                      validation_data=test_ds, validation_steps=(
                test_nums // args.batch_size if test_nums % args.batch_size == 0 else test_nums // args.batch_size + 1))
        his = h.history
        loss = his.get('loss')[0]
        val_loss = his.get('val_loss')[0]
        if val_loss < min_loss:
            min_loss = val_loss
            model.save_weights(model_path)
            print('Epoch:', epoch + 1, ',loss=', loss, 'val_loss:', val_loss, 'save')
        else:
            print('Epoch:', epoch + 1, ',loss=', loss, 'val_loss:', val_loss)
        epoch_list.append(epoch)
        loss_list.append(loss)
        val_loss_list.append(val_loss)
        # 检查并创建 loss 目录（如果不存在）
        if args.loss_dir and not os.path.exists(args.loss_dir):
            os.makedirs(args.loss_dir, exist_ok=True)
            print(f"Directory {args.loss_dir} created.")
        with open(args.loss_dir + filename + '.json', mode='w') as f:
            json.dump({'epoch': epoch_list, 'loss': loss_list, 'val_loss': val_loss_list}, f)


def eval(args, model):
    filename = os.path.basename(__file__).split('.')[0] + '_' + str(args.channel_type) + '_tcn' + str(
        args.transmit_channel_num) + '_snrdb' + str(args.snr_low_eval) + 'to' + str(
        args.snr_up_eval) + '_bs' + str(args.batch_size) + '_lr' + str(args.learning_rate)
    model_path = args.model_dir + filename + '.h5'
    model.load_weights(model_path)
    snr_list = []
    mse_list = []
    psnr_list = []
    for snrdb in range(args.snr_low_eval, args.snr_up_eval + 1):
        imse = []
        # test 10 times each snr
        for i in range(0, 10):
            if args.channel_type == 'awgn':
                (_, _), (test_ds, test_nums) = dataset_cifar10.get_dataset_snr(snrdb)
            elif args.channel_type == 'slow_fading' or args.channel_type == 'slow_fading_eq':
                (_, _), (test_ds, test_nums) = dataset_cifar10.get_dataset_snr_and_h(snrdb)
            test_ds = test_ds.shuffle(buffer_size=test_nums)
            test_ds = test_ds.batch(args.batch_size)
            mse = model.evaluate(test_ds)
            imse.append(mse)
        mse = np.mean(imse)
        psnr = 10 * np.log10(255 ** 2 / mse)
        snr_list.append(snrdb)
        mse_list.append(mse)
        psnr_list.append(psnr)
        with open(args.eval_dir + filename + '.json', mode='w') as f:
            json.dump({'snr': snr_list, 'mse': mse_list, 'psnr': psnr_list}, f)


def eval_burst(args):
    input_imgs = Input(shape=(32, 32, 3))
    input_snrdb = Input(shape=(1,))
    input_b_prob = Input(shape=(1,))
    input_b_stddev = Input(shape=(1,))
    normal_imgs = Lambda(lambda x: x / 255, name='normal')(input_imgs)
    encoder = Attention_Encoder(normal_imgs, input_snrdb, args.transmit_channel_num)
    rv = Channel(channel_type='burst')(encoder, input_snrdb, b_prob=input_b_prob, b_stddev=input_b_stddev)
    decoder = Attention_Decoder(rv, input_snrdb)
    rv_imgs = Lambda(lambda x: x * 255, name='denormal')(decoder)
    model = Model(inputs=[input_imgs, input_snrdb, input_b_prob, input_b_stddev], outputs=rv_imgs)
    model.compile(Adam(args.learning_rate), 'mse')

    filename = os.path.basename(__file__).split('.')[0] + '_' + str(args.channel_type) + '_tcn' + str(
        args.transmit_channel_num) + '_snrdb' + str(args.snr_low_eval) + 'to' + str(
        args.snr_up_eval) + '_bs' + str(args.batch_size) + '_lr' + str(args.learning_rate)
    model_path = args.model_dir + filename + '.h5'
    model.load_weights(model_path)
    prob_list = []
    psnr_list = []
    for b_prob in np.arange(0, 0.225, 0.025):
        imse = []
        # test 10 times each snr
        for i in range(0, 10):
            (_, _), (test_ds, test_nums) = dataset_cifar10.get_test_dataset_burst(args.b_snr_eval, b_prob,
                                                                                  args.input_b_stddev)
            test_ds = test_ds.shuffle(buffer_size=test_nums)
            test_ds = test_ds.batch(args.batch_size)
            mse = model.evaluate(test_ds)
            imse.append(mse)
        mse = np.mean(imse)
        psnr = 10 * np.log10(255 ** 2 / mse)
        prob_list.append(b_prob)
        psnr_list.append(psnr)
        with open(args.eval_dir + 'snr_evaldb' + str(args.snr_eval) + '_burst_sigma' + str(
                args.b_sigma) + filename + '.json', mode='w') as f:
            json.dump({'prob': prob_list, 'psnr': psnr_list}, f)


def main(args):
    # construct encoder-decoder model
    input_imgs = Input(shape=(32, 32, 3))
    input_snrdb = Input(shape=(1,))
    input_h_real = Input(shape=(1,))
    input_h_imag = Input(shape=(1,))
    normal_imgs = Lambda(lambda x: x / 255, name='normal')(input_imgs)
    encoder = Attention_Encoder(normal_imgs, input_snrdb, args.transmit_channel_num)
    if args.channel_type == 'awgn':
        rv = Channel(channel_type='awgn')(encoder, input_snrdb)
    elif args.channel_type == 'slow_fading':
        rv = Channel(channel_type='slow_fading')(encoder, input_snrdb, input_h_real, input_h_imag)
    elif args.channel_type == 'slow_fading_eq':
        rv = Channel(channel_type='slow_fading_eq')(encoder, input_snrdb, input_h_real, input_h_imag)
    decoder = Attention_Decoder(rv, input_snrdb)
    rv_imgs = Lambda(lambda x: x * 255, name='denormal')(decoder)
    if args.channel_type == 'awgn':
        model = Model(inputs=[input_imgs, input_snrdb], outputs=rv_imgs)
    elif args.channel_type == 'slow_fading' or args.channel_type == 'slow_fading_eq':
        model = Model(inputs=[input_imgs, input_snrdb, input_h_real, input_h_imag], outputs=rv_imgs)
    model.compile(Adam(args.learning_rate), 'mse')
    model.summary()
    if args.command == 'train':
        train(args, model)
    elif args.command == 'eval':
        eval(args, model)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", help='trains/eval/eval_burst') # 指定模式 trains（训练）/eval（评估）/eval_burst（评估突发噪声场景）
    parser.add_argument("-ct", '--channel_type', help="awgn/slow_fading/slow_fading_eq/burst") # 指定信道
    parser.add_argument("-md", '--model_dir', help="dir for model", default='model/') # 需要手动创建model文件夹用于保存训练好的模型文件，这里只是给了默认的字符串，但不会自动创建
    parser.add_argument("-lmp", '--load_model_path', help="model path for loading") # 指定是否使用预训练模型，如使用需要指定预训练模型的路径
    parser.add_argument("-bs", "--batch_size", help="Batch size for training", default=128, type=int)
    parser.add_argument("-e", "--epochs", help="epochs for training", default=1280, type=int)
    parser.add_argument("-lr", "--learning_rate", help="learning_rate for training", default=0.0001, type=float)
    parser.add_argument("-tcn", "--transmit_channel_num", help="transmit_channel_num for djscc model", default=16,
                        type=int)
    parser.add_argument("-snr_low_train", "--snr_low_train", help="snr_low for training", default=0, type=int)
    parser.add_argument("-snr_up_train", "--snr_up_train", help="snr_up for training", default=20, type=int)
    parser.add_argument("-snr_low_eval", "--snr_low_eval", help="snr_low for evaluation", default=0, type=int)
    parser.add_argument("-snr_up_eval", "--snr_up_eval", help="snr_up for evaluation", default=20, type=int)
    parser.add_argument("-ldd", "--loss_dir", help="loss_dir for training", default='loss/') # 需要手动创建loss文件夹用于保存loss，不会自动创建
    parser.add_argument("-ed", "--eval_dir", help="eval_dir", default='eval/')
    parser.add_argument("-b_snr_eval", "--burst_snr_eval", help="snr_eval for eval_burst", default=10, type=int)
    parser.add_argument("-b_stddev", "--burst_standard_derivation", help="burst_standard_derivation for eval_burst",
                        default=0., type=float)
    global args
    args = parser.parse_args()
    print("#######################################")
    print("Current execution paramenters:")
    for arg, value in sorted(vars(args).items()):
        print("{}: {}".format(arg, value))
    print("#######################################")
    main(args)
