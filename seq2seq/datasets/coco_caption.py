import os
import logging
from random import randrange
from collections import OrderedDict
import torch
from torch.nn.utils.rnn import pack_padded_sequence
import torchvision.datasets as dset
import torchvision.transforms as transforms
from PIL import ImageFile

from seq2seq.tools.tokenizer import Tokenizer, BPETokenizer, CharTokenizer
from seq2seq.tools.config import EOS, BOS, PAD, LANGUAGE_TOKENS
ImageFile.LOAD_TRUNCATED_IMAGES = True


def imagenet_transform(scale_size=256, input_size=224, train=True, allow_var_size=False):
    normalize = {'mean': [0.485, 0.456, 0.406],
                 'std': [0.229, 0.224, 0.225]}

    if train:
        return transforms.Compose([
            transforms.Scale(scale_size),
            transforms.RandomCrop(input_size),
            transforms.RandomHorizontalFlip(),
            transforms.ToTensor(),
            transforms.Normalize(**normalize)
        ])
    elif allow_var_size:
        return transforms.Compose([
            transforms.Scale(scale_size),
            transforms.ToTensor(),
            transforms.Normalize(**normalize)
        ])
    else:
        return transforms.Compose([
            transforms.Scale(scale_size),
            transforms.CenterCrop(input_size),
            transforms.ToTensor(),
            transforms.Normalize(**normalize)
        ])


def create_padded_caption_batch(max_length=100, batch_first=False, sort=False, pack=False):
    def collate(img_seq_tuple):

        if sort or pack:  # packing requires a sorted batch by length
            img_seq_tuple.sort(key=lambda p: len(p[1]), reverse=True)
        imgs, seqs = zip(*img_seq_tuple)
        imgs = torch.cat([img.unsqueeze(0) for img in imgs], 0)
        lengths = [min(len(s), max_length) for s in seqs]
        batch_length = max(lengths)
        seq_tensor = torch.LongTensor(batch_length, len(seqs)).fill_(PAD)
        for i, s in enumerate(seqs):
            end_seq = lengths[i]
            seq_tensor[:end_seq, i].copy_(s[:end_seq])
        if batch_first:
            seq_tensor = seq_tensor.t()
        else:
            imgs = imgs.unsqueeze(0)
        if pack:
            seq_tensor = pack_padded_sequence(
                seq_tensor, lengths, batch_first=batch_first)
        else:
            seq_tensor = (seq_tensor, lengths)
        return (imgs, seq_tensor)
    return collate


class CocoCaptions(object):
    """docstring for Dataset."""
    __tokenizers = {
        'word': Tokenizer,
        'char': CharTokenizer,
        'bpe': BPETokenizer
    }

    def __init__(self, root, img_transform=imagenet_transform,
                 split='train',
                 tokenization='bpe',
                 num_symbols=32000,
                 shared_vocab=True,
                 code_file=None,
                 vocab_file=None,
                 insert_start=[BOS], insert_end=[EOS],
                 mark_language=False,
                 tokenizer=None,
                 sample_caption=True):
        super(CocoCaptions, self).__init__()
        self.shared_vocab = shared_vocab
        self.num_symbols = num_symbols
        self.tokenizer = tokenizer
        self.tokenization = tokenization
        self.insert_start = insert_start
        self.insert_end = insert_end
        self.mark_language = mark_language
        self.code_file = code_file
        self.vocab_file = vocab_file
        self.sample_caption = None
        self.img_transform = img_transform
        if split == 'train':
            path = {'root': os.path.join(root, 'train2014'),
                    'annFile': os.path.join(root, 'annotations/captions_train2014.json')
                    }
            if sample_caption:
                self.sample_caption = randrange
        else:
            path = {'root': os.path.join(root, 'val2014'),
                    'annFile': os.path.join(root, 'annotations/captions_val2014.json')
                    }
            if sample_caption:
                self.sample_caption = lambda l: 0

        self.data = dset.CocoCaptions(root=path['root'], annFile=path[
                                      'annFile'], transform=img_transform(train=(split == 'train')))

        if self.tokenizer is None:
            prefix = os.path.join(root, 'coco')
            if tokenization not in ['bpe', 'char', 'word']:
                raise ValueError("An invalid option for tokenization was used, options are {0}".format(
                    ','.join(['bpe', 'char', 'word'])))

            if tokenization == 'bpe':
                self.code_file = code_file or '{prefix}.{lang}.{tok}.codes_{num_symbols}'.format(
                    prefix=prefix, lang='en', tok=tokenization, num_symbols=num_symbols)
            else:
                num_symbols = ''

            self.vocab_file = vocab_file or '{prefix}.{lang}.{tok}.vocab{num_symbols}'.format(
                prefix=prefix, lang='en', tok=tokenization, num_symbols=num_symbols)
            self.generate_tokenizer()

    def generate_tokenizer(self):
        additional_tokens = None
        if self.mark_language:
            additional_tokens = [LANGUAGE_TOKENS['en']]

        if self.tokenization == 'bpe':
            tokz = BPETokenizer(self.code_file,
                                vocab_file=self.vocab_file,
                                num_symbols=self.num_symbols,
                                additional_tokens=additional_tokens)
            if not hasattr(tokz, 'bpe'):
                sentences = (d['caption']
                             for d in self.data.coco.anns.values())
                tokz.learn_bpe(sentences, from_filenames=False)
        else:
            tokz = self.__tokenizers[self.tokenization](
                vocab_file=self.vocab_file,
                additional_tokens=additional_tokens)

        if not hasattr(tokz, 'vocab'):
            sentences = (d['caption'] for d in self.data.coco.anns.values())
            logging.info('generating vocabulary. saving to %s' %
                         self.vocab_file)
            tokz.get_vocab(sentences, from_filenames=False)
            tokz.save_vocab(self.vocab_file)
        self.tokenizer = tokz

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[idx] for idx in range(index.start or 0, index.stop or len(self), index.step or 1)]
        img, captions = self.data[index]
        insert_start = self.insert_start
        insert_end = self.insert_end

        def transform(t):
            return self.tokenizer.tokenize(t,
                                           insert_start=insert_start,
                                           insert_end=insert_end)
        if self.sample_caption is None:
            captions = [transform(c) for c in captions]
        else:
            captions = transform(
                captions[self.sample_caption(len(captions))])
        return (img, captions)

    def __len__(self):
        return len(self.data)

    def get_loader(self, batch_size=1, shuffle=False, pack=False, sampler=None, num_workers=0,
                   max_length=100, batch_first=False, pin_memory=False, drop_last=False):
        collate_fn = create_padded_caption_batch(
            max_length=max_length, pack=pack, batch_first=batch_first)
        return torch.utils.data.DataLoader(self,
                                           batch_size=batch_size,
                                           collate_fn=collate_fn,
                                           sampler=sampler,
                                           shuffle=shuffle,
                                           num_workers=num_workers,
                                           pin_memory=pin_memory,
                                           drop_last=drop_last)

    @property
    def tokenizers(self):
        return OrderedDict(img=self.img_transform, en=self.tokenizer)
