import faiss
from sentence_transformers import SentenceTransformer
import os
import torch
import sys
from tqdm import tqdm, trange
import time
import ir_datasets, ir_measures
from ir_measures import *

LOCAL = True if sys.platform == 'win32' else False
model_name = "studio-ousia/luke-base"
model_save_path = f'output/bi-encoder_margin-mse_{model_name.split("/")[-1]}'
run_output_path = model_save_path + '/Run.txt'
device = 'cpu' if LOCAL else 'cuda:2'

# We use the Bi-Encoder to encode all passages, so that we can use it with sematic search
model = SentenceTransformer(model_save_path, device=device)
embedding_dim = model.get_sentence_embedding_dimension()
model.max_seq_length = 512  # Truncate long passages to 512 tokens
print(f'{model_save_path} model loaded.')

### Data files
if LOCAL:
    data_folder = r'C:\Users\sajad\PycharmProjects\chameleon_entity_linking\msmarco'
else:
    data_folder = '/home/sajadeb/msmarco'

### Read the corpus files, that contain all the passages. Store them in the corpus dict
print('Loading collection...')
# corpus = {}
pids = []
corpus = []
corpus_filepath = os.path.join(data_folder, 'collection.tsv')
with open(corpus_filepath, 'r', encoding='utf8') as f:
    for line in tqdm(f):
        pid, passage = line.strip().split("\t")
        # corpus[pid] = passage.strip()
        pids.append(pid)
        corpus.append(passage.strip())

# check whether faiss index exists
if os.path.exists(os.path.join(model_save_path, 'faiss.index')):
    index = faiss.read_index(os.path.join(model_save_path, 'faiss.index'))
    print(f'Index loaded. Index size: {index.ntotal}')
else:
    for x in trange(9, desc='Encoding corpus'):
        corpus_embeddings = model.encode(corpus[x * 1000000:(x + 1) * 1000000], convert_to_tensor=True, show_progress_bar=True, batch_size=128)
        torch.save(corpus_embeddings, os.path.join(model_save_path, f'corpus_tensor_{x + 1}.pt'))

    index = faiss.IndexFlatL2(embedding_dim)
    print(index.is_trained)

    for i in trange(1, 10, desc='Creating index'):
        all_corpus = torch.load(os.path.join(model_save_path, f'corpus_tensor_{i}.pt'), map_location=torch.device(device)).detach().cpu().numpy()
        index.add(all_corpus)

    print(index.ntotal)
    faiss.write_index(index, os.path.join(model_save_path, 'faiss.index'))
    print(f'Index saved. Index size: {index.ntotal}')


queries_filepath = os.path.join(data_folder, 'queries.dev.small.tsv')
qids = []
queries = []
with open(queries_filepath, 'r', encoding='utf-8') as fIn:
    for line in fIn:
        qid, query = line.strip().split("\t")
        qids.append(qid)
        queries.append(query.strip())

top_k = 1000
xq = model.encode(queries)
start_time = time.time()
D, I = index.search(xq, top_k)
print(f'Search time: {time.strftime("%H:%M:%S", time.gmtime(time.time() - start_time))}')

print('Writing the result to file...')
with open(run_output_path, 'w', encoding='utf-8') as fOut:
    for qid in range(len(I)):
        for rank in range(10):
            fOut.write(f'{qids[qid]} Q0 {pids[I[qid][rank]]} {rank+1} {1/(rank+1):.7f} BiEncoder_Retrieval\n')

print('Evaluation...')
qrels = ir_datasets.load('msmarco-passage/dev/small').qrels_iter()
run = ir_measures.read_trec_run(run_output_path)
print(ir_measures.calc_aggregate([nDCG@10, P@10, AP@10, RR@10, R@10], qrels, run))
