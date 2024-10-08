import torch
import torch.nn as nn
import torch.nn.functional as func

from common.utils.embedding import WordEmbedding
import common.common_config as common_conf
import random
import numpy as np

class Encoder(nn.Module):
    def __init__(self, conf, ip_vocab):
        super().__init__()
        self.input_dim = ip_vocab
        self.emb_dim = conf.enc_emb_dim
        self.enc_hid_dim = conf.enc_hidden_size
        self.dec_hid_dim = conf.dec_hidden_size
        self.dropout = conf.dropout

        self.embedding = nn.Embedding(self.input_dim, self.emb_dim)
        self.rnn = nn.GRU(self.emb_dim, self.enc_hid_dim, bidirectional=True)
        self.fc = nn.Linear(self.enc_hid_dim * 2, self.dec_hid_dim)
        self.dropout = nn.Dropout(self.dropout)

    def forward(self, x_):
        embedded = self.dropout(self.embedding(x_))
        outputs, hidden = self.rnn(embedded)
        hidden = torch.tanh(self.fc(torch.cat((hidden[-2, :, :], hidden[-1, :, :]), dim=1)))
        return outputs, hidden


class Attention(nn.Module):
    def __init__(self, enc_hid_dim, dec_hid_dim):
        super().__init__()
        self.attn = nn.Linear((enc_hid_dim * 2) + dec_hid_dim, dec_hid_dim)
        self.v = nn.Parameter(torch.rand(dec_hid_dim))

    def forward(self, hidden, encoder_outputs):
        batch_size = encoder_outputs.shape[1]
        src_len = encoder_outputs.shape[0]
        hidden = hidden.unsqueeze(1).repeat(1, src_len, 1)
        encoder_outputs = encoder_outputs.permute(1, 0, 2)
        energy = torch.tanh(self.attn(torch.cat((hidden, encoder_outputs), dim=2)))
        energy = energy.permute(0, 2, 1)
        v = self.v.repeat(batch_size, 1).unsqueeze(1)
        attention = torch.bmm(v, energy).squeeze(1)
        return func.softmax(attention, dim=1)


class Decoder(nn.Module):
    def __init__(self, conf, op_vocab, attention):
        super().__init__()
        self.output_dim = op_vocab
        self.emb_dim = conf.dec_emb_dim
        self.enc_hid_dim = conf.enc_hidden_size
        self.dec_hid_dim = conf.dec_hidden_size
        self.dropout_prob = conf.dropout
        self.attention = attention

        self.embedding = nn.Embedding(self.output_dim, self.emb_dim)
        self.rnn = nn.GRU((self.enc_hid_dim * 2) + self.emb_dim, self.dec_hid_dim)
        self.out = nn.Linear((self.enc_hid_dim * 2) + self.dec_hid_dim + self.emb_dim, self.output_dim)
        self.dropout = nn.Dropout(self.dropout_prob)

    def forward(self, input, hidden, encoder_outputs):
        input = input.unsqueeze(0)
        embedded = self.dropout(self.embedding(input))
        a = self.attention(hidden, encoder_outputs)
        a = a.unsqueeze(1)
        encoder_outputs = encoder_outputs.permute(1, 0, 2)
        weighted = torch.bmm(a, encoder_outputs)
        weighted = weighted.permute(1, 0, 2)
        rnn_input = torch.cat((embedded, weighted), dim=2)
        output, hidden = self.rnn(rnn_input, hidden.unsqueeze(0))
        assert (output == hidden).all()
        embedded = embedded.squeeze(0)
        output = output.squeeze(0)
        weighted = weighted.squeeze(0)
        output = self.out(torch.cat((output, weighted, embedded), dim=1))
        return output, hidden.squeeze(0)


class Seq2SeqAttention(nn.Module):
    def __init__(self, encoder, decoder):
        super().__init__()
        self.encoder = encoder
        self.decoder = decoder

    def forward(self, x, y, teacher_forcing=0.5):
        batch_size = x.shape[1]
        max_len = y.shape[0]
        trg_vocab_size = self.decoder.output_dim
        outputs = torch.zeros(max_len, batch_size, trg_vocab_size)
        encoder_outputs, hidden = self.encoder(x)

        # _BOS_IX = self.decoder.word_embed.word_ix.objs_to_ints[common_conf.BOS_TOKEN]
        next_timestep_input = torch.from_numpy(np.ones(batch_size)).to(dtype=torch.long)

        # input = y[0, :]
        for t in range(0, max_len):
            output, hidden = self.decoder(next_timestep_input, hidden, encoder_outputs)
            outputs[t] = output
            teacher_force = random.random() < teacher_forcing
            top1 = output.argmax(1)
            next_timestep_input = y[t] if teacher_force else top1

        return outputs
