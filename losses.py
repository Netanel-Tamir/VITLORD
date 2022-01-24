from torchvision.transforms import Resize
from torchvision import transforms
import torch
import torch.nn.functional as F

from extractor import VitExtractor

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')


class LossG(torch.nn.Module):

    def __init__(self, cfg):
        super().__init__()

        self.cfg = cfg
        self.extractor = VitExtractor(model_name=cfg['dino_model_name'], device=device)

        imagenet_norm = transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225))
        global_resize_transform = Resize(cfg['dino_global_patch_size'], max_size=480)

        self.global_transform = transforms.Compose([global_resize_transform])

        self.lambdas = dict(
            content_embedding_reg = cfg['content_embedding_reg'],
            lambda_cls=cfg['lambda_global_cls'],
            lambda_ssim=cfg['lambda_global_ssim'],
            lambda_identity=cfg['lambda_global_identity']
        )

    def forward(self, outputs, inputs, content_embedding):
        # self.update_lambda_config(inputs['step'])
        losses = {}
        loss_G = 0

        if self.lambdas['lambda_ssim'] > 0:
            losses['lambda_ssim'] = self.calculate_global_ssim_loss(outputs, inputs)
            loss_G += losses['lambda_ssim'] * self.lambdas['lambda_ssim']

        if self.lambdas['lambda_cls'] > 0:
            losses['lambda_cls'] = self.calculate_crop_cls_loss(outputs, inputs)
            loss_G += losses['lambda_cls'] * self.lambdas['lambda_cls']

        if self.lambdas['lambda_identity'] > 0:
            losses['lambda_identity'] = self.calculate_global_id_loss(outputs, inputs)
            loss_G += losses['lambda_identity'] * self.lambdas['lambda_identity']
        
        if self.lambdas['content_embedding_reg'] > 0:
            loss_G += self.lambdas['content_embedding_reg'] * torch.norm(content_embedding) ** 2
          
        losses['loss'] = loss_G
        return losses

    def calculate_global_ssim_loss(self, outputs, inputs):
        loss = 0.0
        for a, b in zip(inputs, outputs):  # avoid memory limitations
            a = self.global_transform(a)
            b = self.global_transform(b)
            with torch.no_grad():
                target_keys_self_sim = self.extractor.get_keys_self_sim_from_input(a.unsqueeze(0), layer_num=11)
            keys_ssim = self.extractor.get_keys_self_sim_from_input(b.unsqueeze(0), layer_num=11)
            loss += F.mse_loss(keys_ssim, target_keys_self_sim)
        return loss

    def calculate_crop_cls_loss(self, outputs, inputs):
        loss = 0.0
        for a, b in zip(outputs, inputs):  # avoid memory limitations
            a = self.global_transform(a).unsqueeze(0).to(device)
            b = self.global_transform(b).unsqueeze(0).to(device)
            cls_token = self.extractor.get_feature_from_input(a)[-1][0, 0, :]
            with torch.no_grad():
                target_cls_token = self.extractor.get_feature_from_input(b)[-1][0, 0, :]
            loss += F.mse_loss(cls_token, target_cls_token)
        return loss

    def calculate_global_id_loss(self, outputs, inputs):
        loss = 0.0
        for a, b in zip(inputs, outputs):
            a = self.global_transform(a)
            b = self.global_transform(b)
            with torch.no_grad():
                keys_a = self.extractor.get_keys_from_input(a.unsqueeze(0), 11)
            keys_b = self.extractor.get_keys_from_input(b.unsqueeze(0), 11)
            loss += F.mse_loss(keys_a, keys_b)
        return loss

class NaiveLoss(torch.nn.Module):
    def __init__(self, cfg):
        super().__init__()
        
    def forward(self, outputs, inputs, content_embedding):
        l1_loss = torch.nn.L1Loss(reduction='mean')
        l2_loss = torch.nn.MSELoss()
        reg_factor = 1e-3
        return {'loss': l1_loss(inputs, outputs) + l2_loss(inputs, outputs) + reg_factor * torch.norm(content_embedding) ** 2}