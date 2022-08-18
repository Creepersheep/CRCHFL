import copy
import torch
import torch.nn as nn
import numpy as np
from torch.utils.data import DataLoader
import os
from tqdm import tqdm

from .fed_client import Client
from .fed_optim_variables import *
from .fed_scheduler import Scheduler

import sys
sys.path.append("../")

from fusion import ActionPredModel
from dataloader import ImgData, ActionData, MultiImgData
from config import *
from utils.one_hot import label2onehot

class EdgeServer():
    def __init__(self, server_id, config, test_data, aug_seq, edges_dict, training_config, tensorboard, scheduler):
        self.id = server_id
        self.clients_num = len(config)
        self.clients_dict = {}
        self.clients_log = {}
        self.avgModel = None
        self.edges_dict = edges_dict
        self.epochs = training_config['epochs']
        self.batch_size = training_config['batch_size']
        self.model = ActionPredModel().to(device).eval()
        self.tb = tensorboard
        self.eval_data = test_data
        self.fed_cnt = 0
        self.softmax = nn.Softmax(dim=1)
        self.mse_loss = nn.MSELoss().to(device)
        self.mce_loss = nn.CrossEntropyLoss().to(device)
        self.scheduler = scheduler

        self.clients = []
        for i in range(self.clients_num):
            cid = 'Vehicle'+str(i)
            self.clients.append(Client(self.id, cid, config[cid], self.eval_data, aug_seq, self.clients_dict,
                                       self.clients_log, training_config, tensorboard, scheduler))
            print('Client %s.%s is initialized!' % (self.id, cid))

    def run(self):
        for i in range(self.clients_num):
            self.clients[i].train()

    def FedAvg(self):
        w_avg = copy.deepcopy(self.clients_dict['Vehicle0'])
        for k in w_avg.keys():
            for i in range(1, len(self.clients_dict)):
                w_avg[k] += self.clients_dict['Vehicle' + str(i)][k]
            w_avg[k] = torch.div(w_avg[k], len(self.clients_dict))

        self.avgModel = w_avg

        eval_loss, eval_acc = self.Evaluate()
        self.tb.add_scalar('%s.Fed.Eval.Loss' % self.id, eval_loss, self.fed_cnt)
        self.tb.add_scalar('%s.Fed.Eval.Accuracy' % self.id, eval_acc, self.fed_cnt)
        log_info = "[%d-th %s Federated!] [Edge.Fed.Eval.Loss: %f, Edge.Fed.Eval.Accuracy: %f]" % (self.fed_cnt, self.id, eval_loss, eval_acc)
        print(log_info)
        self.fed_cnt += 1

        self.edges_dict[self.id] = self.avgModel
        ret = self.scheduler.transfer_model()
        if not ret:
            print("Initialized data size has been used up, so exit!")
            sys.exit()

    def SinkModelToClients(self):
        for client in self.clients:
            client.updated_model = self.avgModel
            ret = self.scheduler.transfer_model()
            if not ret:
                print("Initialized data size has been used up, so exit!")
                sys.exit()

    def PreparePretrainData(self):
        data = []
        for client in self.clients:
            data += client.PreparePretrainData()

        ret = self.scheduler.transfer_entries(len(data) * self.batch_size)
        if not ret:
            print("Initialized data size is not enough to transfer pretaining data, so exit!")
            sys.exit()

        return data

    def Evaluate(self):
        self.model.load_state_dict(self.avgModel)
        self.model.eval()

        dataloader, action, data_len, batch_cnt = self.eval_data

        right_cnt = 0
        avg_loss1_sum = 0.0
        avg_loss2_sum = 0.0

        loss = 0.0
        steer_acc = 0.0

        with torch.no_grad():
            for names, imgs_f, imgs_l, imgs_r, imgs_b in tqdm(dataloader):
                action_batch = action.getitems(names)
                st_action, tb_action = action_batch[:, 1], action_batch[:, 0:3:2]

                imgs_f = imgs_f.to(device)
                imgs_l = imgs_l.to(device)
                imgs_r = imgs_r.to(device)
                imgs_b = imgs_b.to(device)

                out_thro_brake, out_steer = self.model(imgs_f, imgs_l, imgs_r, imgs_b)

                thro_brake = tb_action.reshape([self.batch_size, -1])
                avg_loss1 = self.mse_loss(out_thro_brake, Tensor(thro_brake))

                steer = st_action.reshape([self.batch_size, -1])
                label = steer.squeeze()
                steer = Tensor(label2onehot(steer, 7))
                avg_loss2 = self.mce_loss(out_steer, steer)

                avg_loss1_sum += avg_loss1
                avg_loss2_sum += avg_loss2

                out_prob = self.softmax(out_steer)

                out_prob = np.argmax(out_prob.detach().cpu().numpy(), axis=1)

                pred_res = out_prob==np.array(label)
                right_cnt += sum(pred_res)

            loss1 = avg_loss1_sum / batch_cnt
            loss2 = avg_loss2_sum / batch_cnt
            loss = loss1.item() + loss2.item()

            steer_acc = right_cnt / data_len

        return loss, steer_acc

class CloudServer():
    def __init__(self, aug_seq, training_config, tensorboard):
        from .fed_config import config
        self.edges_num = len(config) - 1
        self.edges_dict = {}
        self.pretrain_data = None
        self.pretrain_model = ActionPredModel().to(device)
        self.avgModel = self.pretrain_model.state_dict()
        self.pretrain_config = training_config
        self.tb = tensorboard
        self.epochs = training_config['epochs']

        self.softmax = nn.Softmax(dim=1)
        self.mse_loss = nn.MSELoss().to(device)
        self.mce_loss = nn.CrossEntropyLoss().to(device)
        self.fed_cnt = 0

        def build_eval_data(conf):
            dataset = MultiImgData(conf['test']['dataset'], None, data_transform)
            action = ActionData(config['test']['action'])

            dataloader = DataLoader(dataset,
                    batch_size=self.pretrain_config['batch_size'],
                    shuffle=True,
                    num_workers=0,
                    drop_last=True)

            data_len = len(dataloader) * self.pretrain_config['batch_size']
            batch_cnt = len(dataloader)

            return dataloader, action, data_len, batch_cnt

        self.eval_data = build_eval_data(config)

        self.scheduler = Scheduler(training_config['data_constraint'], 150, 450 * 4)

        self.edges = []
        for i in range(self.edges_num):
            eid = 'Edge'+str(i)
            self.edges.append(EdgeServer(eid, config[eid], self.eval_data, aug_seq, self.edges_dict,
                                         training_config, tensorboard, self.scheduler))

    def train(self):
        edge_fed_cnt = 0
        for j in range(self.epochs // edge_fed_interval):
            for edge in self.edges:
                edge.run()

            edge_fed_cnt += 1
            if edge_fed_cnt == cloud_fed_interval:
                edge_fed_cnt = 0
                self.FedAvg()
                self.SinkModelToEdges()
                for edge in self.edges:
                    edge.SinkModelToClients()
                save_path = ACTION_MODEL_PATH + "FL_%d_action.pth" % j
                torch.save(self.avgModel, save_path)
            else:
                for edge in self.edges:
                    edge.FedAvg()
                    edge.SinkModelToClients()


    def FedAvg(self):
        for edge in self.edges:
            edge.FedAvg()

        w_avg = copy.deepcopy(self.edges_dict['Edge0'])
        for k in w_avg.keys():
            for i in range(1, len(self.edges_dict)):
                w_avg[k] += self.edges_dict['Edge' + str(i)][k]
            w_avg[k] = torch.div(w_avg[k], len(self.edges_dict))

        self.avgModel = w_avg

        eval_loss, eval_acc = self.Evaluate()
        self.tb.add_scalar('Cloud.Fed.Eval.Loss', eval_loss, self.fed_cnt)
        self.tb.add_scalar('Cloud.Fed.Eval.Accuracy', eval_acc, self.fed_cnt)
        log_info = "[%d-th Cloud Federated!] [Cloud.Fed.Eval.Loss: %f, Cloud.Fed.Eval.Accuracy: %f]" % (self.fed_cnt, eval_loss, eval_acc)
        print(log_info)
        self.fed_cnt += 1

    def SinkModelToEdges(self):
        for edge in self.edges:
            edge.avgModel = self.avgModel
            ret = self.scheduler.transfer_model()
            if not ret:
                print("Initialized data size has been used up, so exit!")
                sys.exit()

    def QueryTrainingLog(self):
        log = {}
        for edge in self.edges:
            log[edge.id] = edges.clients_log
        return log

    def CollectPretrainData(self):
        data = []
        for edge in self.edges:
            data += edge.PreparePretrainData()

        self.pretrain_data = data

    def Pretrain(self):
        parameters = self.pretrain_model.parameters()
        optim = torch.optim.Adam(parameters, lr=self.pretrain_config['lr'], betas=self.pretrain_config['betas'], weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.StepLR(optim, step_size=20, gamma=0.1)

        batch_cnt = len(self.pretrain_data)
        data_len = batch_cnt * self.pretrain_config['batch_size']
        for epoch in range(pretrain_epochs):
            self.pretrain_model.train()

            avg_loss1_sum = 0.0
            avg_loss2_sum = 0.0
            right_cnt = 0
            for data in tqdm(self.pretrain_data):
                data_batch, action_batch = data['dataset'], data['action']
                imgs_f, imgs_l, imgs_r, imgs_b = data_batch[1], data_batch[2], data_batch[3], data_batch[4]

                st_action, tb_action = action_batch[:, 1], action_batch[:, 0:3:2]

                optim.zero_grad()

                imgs_f = imgs_f.to(device)
                imgs_l = imgs_l.to(device)
                imgs_r = imgs_r.to(device)
                imgs_b = imgs_b.to(device)

                out_thro_brake, out_steer = self.pretrain_model(imgs_f, imgs_l, imgs_r, imgs_b)

                thro_brake = tb_action.reshape([self.pretrain_config['batch_size'], -1])
                avg_loss1 = self.mse_loss(out_thro_brake, Tensor(thro_brake))

                steer = st_action.reshape([self.pretrain_config['batch_size'], -1])
                label = steer.squeeze()
                steer = Tensor(label2onehot(steer, 7))
                avg_loss2 = self.mce_loss(out_steer, steer)

                avg_loss1.backward()
                avg_loss2.backward()

                optim.step()

                avg_loss1_sum += avg_loss1
                avg_loss2_sum += avg_loss2

                out_prob = self.softmax(out_steer)

                out_prob = np.argmax(out_prob.detach().cpu().numpy(), axis=1)

                pred_res = out_prob==np.array(label)
                right_cnt += sum(pred_res)

            scheduler.step()

            loss1 = avg_loss1_sum / batch_cnt
            loss2 = avg_loss2_sum / batch_cnt
            loss = loss1.item() + loss2.item()

            steer_acc = right_cnt / data_len

            log_info = "[Pretrain Stage] [Epoch: %d/%d] [Train.Loss: %f, Train.Accuracy: %f]" % (epoch, pretrain_epochs, loss, steer_acc)
            print(log_info)

            self.tb.add_scalar('Cloud.Pretrain.Train.Loss', loss, epoch)
            self.tb.add_scalar('Cloud.Pretrain.Train.Accuracy', steer_acc, epoch)

            if epoch == pretrain_epochs - 1:
                self.avgModel = self.pretrain_model.state_dict()

            eval_loss, eval_acc = self.Evaluate()
            self.tb.add_scalar('Cloud.Pretrain.Eval.Loss', eval_loss, epoch)
            self.tb.add_scalar('Cloud.Pretrain.Eval.Accuracy', eval_acc, epoch)
            log_info = "[Pretrain Stage] [Epoch: %d/%d] [Eval.Loss: %f, Eval.Accuracy: %f]" % (epoch, pretrain_epochs, eval_loss, eval_acc)
            print(log_info)

    def CalcClientsCnt(self):
        cnt = 0
        for edge in self.edges:
            cnt += edge.clients_num

        return cnt

    def Evaluate(self):
        self.pretrain_model.load_state_dict(self.avgModel)
        self.pretrain_model.eval()

        dataloader, action, data_len, batch_cnt = self.eval_data

        right_cnt = 0
        avg_loss1_sum = 0.0
        avg_loss2_sum = 0.0
        loss = 0.0
        steer_acc = 0.0

        with torch.no_grad():
            for names, imgs_f, imgs_l, imgs_r, imgs_b in tqdm(dataloader):
                action_batch = action.getitems(names)
                st_action, tb_action = action_batch[:, 1], action_batch[:, 0:3:2]

                imgs_f = imgs_f.to(device)
                imgs_l = imgs_l.to(device)
                imgs_r = imgs_r.to(device)
                imgs_b = imgs_b.to(device)

                out_thro_brake, out_steer = self.pretrain_model(imgs_f, imgs_l, imgs_r, imgs_b)

                thro_brake = tb_action.reshape([self.pretrain_config['batch_size'], -1])
                avg_loss1 = self.mse_loss(out_thro_brake, Tensor(thro_brake))

                steer = st_action.reshape([self.pretrain_config['batch_size'], -1])
                label = steer.squeeze()
                steer = Tensor(label2onehot(steer, 7))
                avg_loss2 = self.mce_loss(out_steer, steer)

                avg_loss1_sum += avg_loss1
                avg_loss2_sum += avg_loss2

                out_prob = self.softmax(out_steer)

                out_prob = np.argmax(out_prob.detach().cpu().numpy(), axis=1)

                pred_res = out_prob==np.array(label)
                right_cnt += sum(pred_res)

            loss1 = avg_loss1_sum / batch_cnt
            loss2 = avg_loss2_sum / batch_cnt
            loss = loss1.item() + loss2.item()

            steer_acc = right_cnt / data_len

        return loss, steer_acc
