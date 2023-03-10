import time, random, numpy as np, argparse, sys, re, os
from types import SimpleNamespace

import torch
from torch import nn
import torch.nn.functional as F
from torch.utils.data import DataLoader

from bert import BertModel
from optimizer import AdamW
from tqdm import tqdm

from datasets import SentenceClassificationDataset, SentencePairDataset, \
    load_multitask_data, load_multitask_test_data

from evaluation import model_eval_sst,model_eval_multitask, test_model_multitask

from itertools import zip_longest

TQDM_DISABLE=True

# fix the random seed
def seed_everything(seed=11711):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True


BERT_HIDDEN_SIZE = 768
N_SENTIMENT_CLASSES = 5


class MultitaskBERT(nn.Module):
    '''
    This module should use BERT for 3 tasks:

    - Sentiment classification (predict_sentiment)
    - Paraphrase detection (predict_paraphrase)
    - Semantic Textual Similarity (predict_similarity)
    '''
    def __init__(self, config):
        super(MultitaskBERT, self).__init__()
        # You will want to add layers here to perform the downstream tasks.
        # Pretrain mode does not require updating bert paramters.
        self.bert = BertModel.from_pretrained('bert-base-uncased')
        for param in self.bert.parameters():
            if config.option == 'pretrain':
                param.requires_grad = False
            elif config.option == 'finetune':
                param.requires_grad = True
        ### TODO
        self.sentiment_classifier = nn.Linear(BERT_HIDDEN_SIZE, N_SENTIMENT_CLASSES)
        self.paraphrase_predicter = nn.CosineSimilarity(dim=1, eps=1e-6)
        self.similarity_predicter = nn.CosineSimilarity(dim=1, eps=1e-6)
        #cosine similarity
        # self.cosine_similarity = nn.CosineSimilarity(dim=1, eps=1e-6)
        self.dropout = nn.Dropout(config.hidden_dropout_prob)

        


    def forward(self, input_ids, attention_mask):
        'Takes a batch of sentences and produces embeddings for them.'
        # The final BERT embedding is the hidden state of [CLS] token (the first token)
        # Here, you can start by just returning the embeddings straight from BERT.
        # When thinking of improvements, you can later try modifying this
        # (e.g., by adding other layers).
        ### TODO
        outputs = self.bert.forward(input_ids=input_ids, attention_mask=attention_mask) # (batch_size, seq_len, hidden_size)
        #directly return outputs (without any modification?)
        #is this correct?
        return outputs   
        


    def predict_sentiment(self, input_ids, attention_mask):
        '''Given a batch of sentences, outputs logits for classifying sentiment.
        There are 5 sentiment classes:
        (0 - negative, 1- somewhat negative, 2- neutral, 3- somewhat positive, 4- positive)
        Thus, your output should contain 5 logits for each sentence.
        '''
        ### TODO
        outputs = self.forward(input_ids, attention_mask)
        cls_output = outputs["last_hidden_state"][:, 0]  # [CLS] token
        cls_output = self.dropout(cls_output)
        logits = self.sentiment_classifier(cls_output)
        return logits


    def predict_paraphrase(self,
                           input_ids_1, attention_mask_1,
                           input_ids_2, attention_mask_2):
        '''Given a batch of pairs of sentences, outputs a single logit for predicting whether they are paraphrases.
        Note that your output should be unnormalized (a logit); it will be passed to the sigmoid function
        during evaluation, and handled as a logit by the appropriate loss function.
        '''
        ### TODO
        outputs_1 = self.forward(input_ids_1, attention_mask_1)
        outputs_2 = self.forward(input_ids_2, attention_mask_2)
        cls_output_1 = outputs_1["last_hidden_state"][:, 0]  # [CLS] token
        cls_output_2 = outputs_2["last_hidden_state"][:, 0]  # [CLS] token
        cls_output_1 = self.dropout(cls_output_1)
        cls_output_2 = self.dropout(cls_output_2)
        logits = self.paraphrase_predicter(cls_output_1, cls_output_2)
        return logits


    def predict_similarity(self,
                           input_ids_1, attention_mask_1,
                           input_ids_2, attention_mask_2):
        '''Given a batch of pairs of sentences, outputs a single logit corresponding to how similar they are.
        Note that your output should be unnormalized (a logit); it will be passed to the sigmoid function
        during evaluation, and handled as a logit by the appropriate loss function.
        '''
        ### TODO
        outputs_1 = self.forward(input_ids_1, attention_mask_1)
        outputs_2 = self.forward(input_ids_2, attention_mask_2)
        cls_output_1 = outputs_1["last_hidden_state"][:, 0]  # [CLS] token
        cls_output_2 = outputs_2["last_hidden_state"][:, 0]  # [CLS] token
        cls_output_1 = self.dropout(cls_output_1)
        cls_output_2 = self.dropout(cls_output_2)
        logits = self.similarity_predicter(cls_output_1, cls_output_2)
        return logits




def save_model(model, optimizer, args, config, filepath):
    save_info = {
        'model': model.state_dict(),
        'optim': optimizer.state_dict(),
        'args': args,
        'model_config': config,
        'system_rng': random.getstate(),
        'numpy_rng': np.random.get_state(),
        'torch_rng': torch.random.get_rng_state(),
    }

    torch.save(save_info, filepath)
    print(f"save the model to {filepath}")


## Currently only trains on sst dataset
def train_multitask(args):
    device = torch.device('cuda') if args.use_gpu else torch.device('cpu')
    # Load data
    # Create the data and its corresponding datasets and dataloader
    sst_train_data, num_labels,para_train_data, sts_train_data = load_multitask_data(args.sst_train,args.para_train,args.sts_train, split ='train')
    sst_dev_data, num_labels,para_dev_data, sts_dev_data = load_multitask_data(args.sst_dev,args.para_dev,args.sts_dev, split ='train')

    sst_train_data = SentenceClassificationDataset(sst_train_data, args)
    sst_dev_data = SentenceClassificationDataset(sst_dev_data, args)
    #load in additional datasets
    quora_train_data = SentencePairDataset(para_train_data, args)
    quora_dev_data = SentencePairDataset(para_dev_data, args)
    sts_train_data = SentencePairDataset(sts_train_data, args)
    sts_dev_data = SentencePairDataset(sts_dev_data, args)



    sst_train_dataloader = DataLoader(sst_train_data, shuffle=True, batch_size=args.batch_size,
                                      collate_fn=sst_train_data.collate_fn)
    sst_dev_dataloader = DataLoader(sst_dev_data, shuffle=False, batch_size=args.batch_size,
                                    collate_fn=sst_dev_data.collate_fn)
    #load in additional dataloaders
    quora_train_dataloader = DataLoader(quora_train_data, shuffle=True, batch_size=args.batch_size,
                                        collate_fn=quora_train_data.collate_fn)
    quora_dev_dataloader = DataLoader(quora_dev_data, shuffle=False, batch_size=args.batch_size,
                                        collate_fn=quora_dev_data.collate_fn)
    sts_train_dataloader = DataLoader(sts_train_data, shuffle=True, batch_size=args.batch_size,
                                        collate_fn=sts_train_data.collate_fn)
    sts_dev_dataloader = DataLoader(sts_dev_data, shuffle=False, batch_size=args.batch_size,
                                        collate_fn=sts_dev_data.collate_fn)
    

    # Init model
    config = {'hidden_dropout_prob': args.hidden_dropout_prob,
              'num_labels': num_labels,
              'hidden_size': 768,
              'data_dir': '.',
              'option': args.option}

    config = SimpleNamespace(**config)

    model = MultitaskBERT(config)
    model = model.to(device)

    lr = args.lr
    optimizer = AdamW(model.parameters(), lr=lr)
    best_dev_acc = 0

    # Run for the specified number of epochs
    for epoch in range(args.epochs):
        model.train()
        train_loss = 0
        num_batches = 0
        
        combined_dataloader = zip_longest(sst_train_dataloader,quora_train_dataloader,sts_train_dataloader)
        # for batch in tqdm(sst_train_dataloader, desc=f'train-{epoch}', disable=TQDM_DISABLE):
        #     b_ids, b_mask, b_labels = (batch['token_ids'],
        #                                batch['attention_mask'], batch['labels'])

        #     b_ids = b_ids.to(device)
        #     b_mask = b_mask.to(device)
        #     b_labels = b_labels.to(device)

        #     optimizer.zero_grad()
        #     logits = model.predict_sentiment(b_ids, b_mask)
        #     loss = F.cross_entropy(logits, b_labels.view(-1), reduction='sum') / args.batch_size

        #     loss.backward()
        #     optimizer.step()

        #     train_loss += loss.item()
        #     num_batches += 1
        for batch in tqdm(combined_dataloader, desc=f'train-{epoch}'):
            #training for sentiment on sst
            if batch[0] is not None:
                b_ids, b_mask, b_labels = (batch[0]['token_ids'],
                                           batch[0]['attention_mask'], batch[0]['labels'])

                b_ids = b_ids.to(device)
                b_mask = b_mask.to(device)
                b_labels = b_labels.to(device)

                optimizer.zero_grad()
                logits = model.predict_sentiment(b_ids, b_mask)
                loss = F.cross_entropy(logits, b_labels.view(-1), reduction='sum') / args.batch_size

                loss.backward()
                optimizer.step()

                train_loss += loss.item()
                num_batches += 1
            #training for paraphrase on quora
            if batch[1] is not None:
                b_ids_1, b_mask_1, b_ids_2, b_mask_2, b_labels = (batch[1]['token_ids_1'],
                                           batch[1]['attention_mask_1'], batch[1]['token_ids_2'],
                                           batch[1]['attention_mask_2'], batch[1]['labels'])
                                           

                b_ids_1 = b_ids_1.to(device)
                b_mask_1 = b_mask_1.to(device)
                b_ids_2 = b_ids_2.to(device)
                b_mask_2 = b_mask_2.to(device)
                b_labels = b_labels.to(device)

                
                
                logits = model.predict_paraphrase(b_ids_1, b_mask_1, b_ids_2, b_mask_2)
                loss = F.binary_cross_entropy_with_logits(logits, b_labels.view(-1).type(torch.float), reduction='sum') / args.batch_size
                # loss = F.cross_entropy(logits, b_labels.view(-1), reduction='sum') / args.batch_size
                loss.requires_grad = True
                loss.backward()
                optimizer.step()
                optimizer.zero_grad()
                train_loss += loss.item()
                num_batches += 1
            #training for similarity on sts
            if batch[2] is not None:
                b_ids_1, b_mask_1, b_ids_2, b_mask_2, b_labels = (batch[2]['token_ids_1'],
                                           batch[2]['attention_mask_1'], batch[2]['token_ids_2'],
                                           batch[2]['attention_mask_2'], batch[2]['labels'])
                b_ids_1 = b_ids_1.to(device)
                b_mask_1 = b_mask_1.to(device)
                b_ids_2 = b_ids_2.to(device)
                b_mask_2 = b_mask_2.to(device)
                b_labels = b_labels.to(device)

                
                logits = model.predict_similarity(b_ids_1, b_mask_1, b_ids_2, b_mask_2)
                loss = F.mse_loss(logits, b_labels.view(-1), reduction='sum') / args.batch_size
                loss.requires_grad = True
                loss.backward()
                optimizer.step()
                optimizer.zero_grad()
                train_loss += loss.item()
                num_batches += 1

        train_loss = train_loss / (num_batches)

        train_acc, train_f1, *_ = model_eval_multitask(sst_train_dataloader, quora_train_dataloader, sts_train_dataloader, model, device)
        dev_acc, dev_f1, *_ = model_eval_multitask(sst_dev_dataloader, quora_dev_dataloader, sts_dev_dataloader, model, device)
        
        
        if dev_acc > best_dev_acc:
            best_dev_acc = dev_acc
            save_model(model, optimizer, args, config, args.filepath)

        print(f"Epoch {epoch}: train loss :: {train_loss :.3f}, train acc :: {train_acc :.3f}, dev acc :: {dev_acc :.3f}")



def test_model(args):
    with torch.no_grad():
        device = torch.device('cuda') if args.use_gpu else torch.device('cpu')
        saved = torch.load(args.filepath)
        config = saved['model_config']

        model = MultitaskBERT(config)
        model.load_state_dict(saved['model'])
        model = model.to(device)
        print(f"Loaded model to test from {args.filepath}")

        test_model_multitask(args, model, device)


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sst_train", type=str, default="data/ids-sst-train.csv")
    parser.add_argument("--sst_dev", type=str, default="data/ids-sst-dev.csv")
    parser.add_argument("--sst_test", type=str, default="data/ids-sst-test-student.csv")

    parser.add_argument("--para_train", type=str, default="data/quora-train.csv")
    parser.add_argument("--para_dev", type=str, default="data/quora-dev.csv")
    parser.add_argument("--para_test", type=str, default="data/quora-test-student.csv")

    parser.add_argument("--sts_train", type=str, default="data/sts-train.csv")
    parser.add_argument("--sts_dev", type=str, default="data/sts-dev.csv")
    parser.add_argument("--sts_test", type=str, default="data/sts-test-student.csv")

    parser.add_argument("--seed", type=int, default=11711)
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--option", type=str,
                        help='pretrain: the BERT parameters are frozen; finetune: BERT parameters are updated',
                        choices=('pretrain', 'finetune'), default="pretrain")
    parser.add_argument("--use_gpu", action='store_true')

    parser.add_argument("--sst_dev_out", type=str, default="predictions/sst-dev-output.csv")
    parser.add_argument("--sst_test_out", type=str, default="predictions/sst-test-output.csv")

    parser.add_argument("--para_dev_out", type=str, default="predictions/para-dev-output.csv")
    parser.add_argument("--para_test_out", type=str, default="predictions/para-test-output.csv")

    parser.add_argument("--sts_dev_out", type=str, default="predictions/sts-dev-output.csv")
    parser.add_argument("--sts_test_out", type=str, default="predictions/sts-test-output.csv")

    # hyper parameters
    parser.add_argument("--batch_size", help='sst: 64, cfimdb: 8 can fit a 12GB GPU', type=int, default=8)
    parser.add_argument("--hidden_dropout_prob", type=float, default=0.3)
    parser.add_argument("--lr", type=float, help="learning rate, default lr for 'pretrain': 1e-3, 'finetune': 1e-5",
                        default=1e-5)

    args = parser.parse_args()
    return args

if __name__ == "__main__":
    args = get_args()
    args.filepath = f'{args.option}-{args.epochs}-{args.lr}-multitask.pt' # save path
    seed_everything(args.seed)  # fix the seed for reproducibility
    train_multitask(args)
    test_model(args)
