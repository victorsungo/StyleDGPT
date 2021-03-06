import json
import torch
import torch.nn.functional as F
from transformers import GPT2Tokenizer
import os

EPSILON = 1e-10

from .modeling_gpt2 import GPT2LMHeadModel

class ClassificationHead(torch.nn.Module):
    """Classification Head for transformer encoders"""

    def __init__(self, class_size, embed_size):
        super(ClassificationHead, self).__init__()
        self.class_size = class_size
        self.embed_size = embed_size
        self.mlp = torch.nn.Linear(embed_size, class_size)

    def forward(self, hidden_state):
        logits = self.mlp(hidden_state)
        return logits


class Discriminator(torch.nn.Module):
    """Transformer encoder followed by a Classification Head"""

    def __init__(
            self,
            class_size,
            model_name_or_path="gpt2-medium",
            cached_mode=False,
            device='cpu',
            encoder=None,
            tokenizer=None
    ):
        super(Discriminator, self).__init__()
        if tokenizer is not None:
            self.tokenizer = tokenizer
        else:
            self.tokenizer = GPT2Tokenizer.from_pretrained(model_name_or_path)
        if encoder:
            self.encoder = encoder
        else:
            self.encoder = GPT2LMHeadModel.from_pretrained(model_name_or_path).transformer

        self.embed_size = self.encoder.config.hidden_size

        self.classifier_head = ClassificationHead(
            class_size=class_size,
            embed_size=self.embed_size
        )
        self.cached_mode = cached_mode
        self.device = device

    def get_classifier(self):
        return self.classifier_head

    def train_custom(self):
        for param in self.encoder.parameters():
            param.requires_grad = False
        self.classifier_head.train()

    def avg_representation(self, x=None, inputs_embeds=None):
        '''

        Args:
            x: B x seq_len
        Returns:
            avg_hidden: B x embed_size

        '''
        if inputs_embeds is None:
            mask = x.ne(0).unsqueeze(2).repeat(1, 1, self.embed_size).float().to(self.device).detach()
            # hidden, _ = self.encoder.transformer(x)
            hidden, _ = self.encoder(x)
            masked_hidden = hidden * mask
            avg_hidden = torch.sum(masked_hidden, dim=1) / (torch.sum(mask, dim=1).detach() + EPSILON)
        else:
            hidden,_  = self.encoder(inputs_embeds=inputs_embeds)
            avg_hidden = torch.mean(hidden, dim=1)
        return avg_hidden

    def forward(self, x=None, inputs_embeds=None):
        if x is not None:
            x= x.to(self.device)
        if inputs_embeds is not None:
            inputs_embeds = inputs_embeds.to(self.device)

        if self.cached_mode:
            avg_hidden = x
        else:
            avg_hidden = self.avg_representation(x, inputs_embeds)

        logits = self.classifier_head(avg_hidden)
        probs = F.log_softmax(logits, dim=1)
        # probs = logits

        return probs

    @classmethod
    def from_pretrained(cls, model_fi, encoder=None, device='cpu'):
        if os.path.exists(model_fi):
            model_dir = os.path.dirname(model_fi)
            meta_json_file = os.path.join(model_dir, 'classifier_head_meta.json')

            if not os.path.exists(meta_json_file):
                raise OSError(f'The discriminator meta file ({meta_json_file}) is not exists.')

            with open(meta_json_file, encoding='utf8')as p:
                meta = json.load(p)

            model = cls(
                class_size=meta['class_size'],
                encoder=encoder,
                tokenizer=1,    # trick to accelerate loading
                device=device
            )

            head_checkpoint = os.path.join(model_fi)
            state_dict = torch.load(head_checkpoint, map_location=device)
            model.classifier_head.load_state_dict(state_dict)

            return model.eval()

        else:
            raise OSError(f'The discriminator model file ({model_fi}) is invalid.')

