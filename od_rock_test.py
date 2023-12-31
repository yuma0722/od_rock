# -*- coding: utf-8 -*-
"""Untitled0.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1Eb56Gb_dkuP-NBI7RHW9qu50g0AW3sjD
"""

# Commented out IPython magic to ensure Python compatibility.
# パッケージのimport
import os.path as osp
import os
import sys
sys.path.append('/content/drive/MyDrive/Colab_Notebooks/od_rock')
import random
import time
import glob
import cv2
import numpy as np
from tqdm import tqdm
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split
import torch
import torch.nn as nn
import torch.nn.init as init
import torch.optim as optim
import torch.utils.data as data

from utils.ssd_model import VOCDataset, DataTransform, Anno_xml2list, od_collate_fn
from utils.ssd_model import SSD
from utils.ssd_model import MultiBoxLoss

from torch.utils.tensorboard import SummaryWriter

# ロガーを初期化
writer = SummaryWriter('runs/experiment_name')



def get_image_path(data_path, filename):
    if os.path.exists(f'{data_path}/{filename}.png'):
        return f'{data_path}/{filename}.png'
    elif os.path.exists(f'{data_path}/{filename}.jpg'):
        return f'{data_path}/{filename}.jpg'
    else:
        raise ValueError(f"No image found for {filename} in {data_path}")
"""
if len(filename_list) > 1:
    filename_list_train, filename_list_val = train_test_split(filename_list, test_size=0.1)
else:
    filename_list_train = filename_list
    filename_list_val = []
"""

data_path = '/content/drive/MyDrive/Colab_Notebooks/od_rock/od_rock_adaptiv'
filename_list = [os.path.split(f)[1].split('.')[0] for f in glob.glob(f'{data_path}/*.xml')]
filename_list_train, filename_list_val = train_test_split(filename_list, test_size=0.3)
train_img_list = [get_image_path(data_path, f) for f in filename_list_train]
train_anno_list = [f'{data_path}/{f}.xml' for f in filename_list_train]
val_img_list = [get_image_path(data_path, f) for f in filename_list_val]
val_anno_list = [f'{data_path}/{f}.xml' for f in filename_list_val]

'''
# データのリストを取得
data_path = '/content/drive/MyDrive/Colab_Notebooks/od_rock/od_rock_mix_real'
filename_list = [os.path.split(f)[1].split('.')[0] for f in glob.glob(f'{data_path}/*.xml')]
filename_list_train, filename_list_val = train_test_split(filename_list, test_size=0.1)
train_img_list = [f'{data_path}/{f}.png' for f in filename_list_train]
train_anno_list = [f'{data_path}/{f}.xml' for f in filename_list_train]
val_img_list = [f'{data_path}/{f}.png' for f in filename_list_val]
val_anno_list = [f'{data_path}/{f}.xml' for f in filename_list_val]
'''

# Datasetを作成
voc_classes = ['rock']

color_mean = (104, 117, 123)  # (BGR)の色の平均値
input_size = 300  # 画像のinputサイズ

train_dataset = VOCDataset(train_img_list,
                           train_anno_list,
                           phase="train",
                           transform=DataTransform(input_size, color_mean),
                           transform_anno=Anno_xml2list(voc_classes))
val_dataset = VOCDataset(val_img_list,
                         val_anno_list,
                         phase="val",
                         transform=DataTransform(input_size, color_mean),
                         transform_anno=Anno_xml2list(voc_classes))

# DataLoaderを作成する
train_dataloader = data.DataLoader(train_dataset,
                                   batch_size=32,
                                   shuffle=True,
                                   collate_fn=od_collate_fn)
val_dataloader = data.DataLoader(val_dataset,
                                 batch_size=3,
                                 shuffle=False,
                                 collate_fn=od_collate_fn)

# 辞書オブジェクトにまとめる
dataloaders_dict = {"train": train_dataloader, "val": val_dataloader}

# SSD300の設定
ssd_cfg = {
    'num_classes': 2,  # 背景クラスを含めた合計クラス数
    'input_size': 300,  # 画像の入力サイズ
    'bbox_aspect_num': [4, 6, 6, 6, 4, 4],  # 出力するDBoxのアスペクト比の種類
    'feature_maps': [38, 19, 10, 5, 3, 1],  # 各sourceの画像サイズ
    'steps': [8, 16, 32, 64, 100, 300],  # DBOXの大きさを決める
    'min_sizes': [21, 45, 99, 153, 207, 261],  # DBOXの大きさを決める
    'max_sizes': [45, 99, 153, 207, 261, 315],  # DBOXの大きさを決める
    'aspect_ratios': [[2], [2, 3], [2, 3], [2, 3], [2], [2]],
}


# SSDネットワークモデル
net = SSD(phase="train", cfg=ssd_cfg)

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
net.to(device)

# SSDの初期の重みを設定
vgg_weights = torch.load('/content/drive/MyDrive/Colab_Notebooks/od_rock/weights/vgg16_reducedfc.pth')
net.vgg.load_state_dict(vgg_weights)

# ssdのその他のネットワークの重みはHeの初期値で初期化
def weights_init(m):
    if isinstance(m, nn.Conv2d):
        init.kaiming_normal_(m.weight.data)
        if m.bias is not None:  # バイアス項がある場合
            nn.init.constant_(m.bias, 0.0)

# Heの初期値を適用
net.extras.apply(weights_init)
net.loc.apply(weights_init)
net.conf.apply(weights_init)

# GPUが使えるかを確認
device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
print("使用デバイス：", device)
print('ネットワーク設定完了：学習済みの重みをロードしました')

# 損失関数の設定
criterion = MultiBoxLoss(jaccard_thresh=0.5, neg_pos=3, device=device)

# 最適化手法の設定
optimizer = optim.SGD(net.parameters(), lr=1e-3, momentum=0.9, weight_decay=5e-4)

#損失の変化をプロット
def plot_loss(logs):
    train_losses = [log['train_loss'] for log in logs]
    val_losses = [log['val_loss'] for log in logs]
    epochs = range(1, len(logs) + 1)

    plt.plot(epochs, train_losses, label='Train Loss')
    plt.plot(epochs, val_losses, label='Val Loss')
    plt.title('Training and Validation Loss')
    plt.xlabel('Epochs')
    plt.ylabel('Loss')
    plt.legend()
    plt.show()

# モデルを学習させる関数を作成
def train_model(net, dataloaders_dict, criterion, optimizer, num_epochs):

    # GPUが使えるかを確認
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    print("使用デバイス：", device)

    # ネットワークをGPUへ
    net.to(device)

    # ネットワークがある程度固定であれば、高速化させる
    torch.backends.cudnn.benchmark = True

    # イテレーションカウンタをセット
    iteration = 1
    epoch_train_loss = 0.0  # epochの損失和
    epoch_val_loss = 0.0  # epochの損失和
    min_loss = 9999
    logs = []


# TensorBoardのSummaryWriterを定義
    writer = SummaryWriter()
#     %load_ext tensorboard
#     %tensorboard --logdir runs

    # epochのループ
    for epoch in range(num_epochs+1):

        # 開始時刻を保存
        t_epoch_start = time.time()
        t_iter_start = time.time()

        # epochごとの訓練と検証のループ
        for phase in ['train', 'val']:
            if phase == 'train':
                net.train()
            else:
                net.eval()

            # データローダーからminibatchずつ取り出すループ
            with tqdm(dataloaders_dict[phase], desc=phase, file=sys.stdout) as iterator:
                for images, targets in iterator:


                    # GPUが使えるならGPUにデータを送る
                    images = images.to(device)
                    targets = [ann.to(device)
                               for ann in targets]  # リストの各要素のテンソルをGPUへ

                    # optimizerを初期化
                    optimizer.zero_grad()

                    # 順伝搬（forward）計算
                    with torch.set_grad_enabled(phase == 'train'):
                        # 順伝搬（forward）計算
                        outputs = net(images)

                        # 損失の計算
                        loss_l, loss_c = criterion(outputs, targets)
                        loss = loss_l + loss_c

                        # 訓練時はバックプロパゲーション
                        if phase == 'train':
                            loss.backward()
                            nn.utils.clip_grad_value_(net.parameters(), clip_value=2.0)
                            optimizer.step()
                            epoch_train_loss += loss.item()
                            iteration += 1
                        # 検証時
                        else:
                            epoch_val_loss += loss.item()

                      # TensorBoardにログを書き込む
                      writer.add_scalar('Train/Loss', train_loss, epoch)
                      writer.add_scalar('Val/Loss', val_loss, epoch)

         # epochのphaseごとのlossと正解率
        t_epoch_finish = time.time()
        print(f'epoch {epoch+1}/{num_epochs} {(t_epoch_finish - t_epoch_start):.4f}sec || train_Loss:{epoch_train_loss:.4f} val_Loss:{epoch_val_loss:.4f}')
        t_epoch_start = time.time()

        # ログを保存
        logs.append({'train_loss': epoch_train_loss, 'val_loss': epoch_val_loss})



        # vallossが小さい、ネットワークを保存する
        if min_loss>epoch_val_loss:
            min_loss=epoch_val_loss
            torch.save(net.state_dict(), '/content/drive/MyDrive/Colab_Notebooks/od_rock/weights/ssd_best_adp.pth')

        epoch_train_loss = 0.0  # epochの損失和
        epoch_val_loss = 0.0  # epochの損失和

    #損失関数のプロット
    plot_loss(logs)

# 学習・検証を実行する
num_epochs = 1000
logs = [] # ログを保存するリスト
train_model(net, dataloaders_dict, criterion, optimizer, num_epochs=num_epochs)