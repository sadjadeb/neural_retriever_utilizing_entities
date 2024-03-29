from model import CrossEncoder
import os
from tqdm import tqdm
import sys
import ir_datasets, ir_measures
from ir_measures import *

LOCAL = True if sys.platform == 'win32' else False
# First, we define the transformer model we want to fine-tune
# model_name = 'distilroberta-base'
model_name = "studio-ousia/luke-base"
model_save_path = f'output/cross-encoder_{model_name.split("/")[-1]}_with-entities-entities'
run_output_path = model_save_path + '/Run.txt'
device = 'cpu' if LOCAL else 'cuda:1'

model = CrossEncoder(model_save_path, device=device, num_labels=1)
print(f'{model_save_path} model loaded.')

### Now we read the MS Marco dataset
if LOCAL:
    data_folder = r'C:\Users\sajad\PycharmProjects\chameleon_entity_linking\msmarco'
else:
    data_folder = '/home/sajadeb/msmarco'

#### Read the corpus files, that contain all the passages. Store them in the corpus dict
print('Loading collection...')
collection = {}
collection_filepath = os.path.join(data_folder, 'collection.tsv')
with open(collection_filepath, 'r', encoding='utf8') as f:
    for line in f:
        pid, passage = line.strip().split("\t")
        collection[pid] = passage.strip()

### Read the test queries, store in queries dict
print('Loading queries...')
queries = {}
queries_filepath = os.path.join(data_folder, 'queries.dev.small.tsv')
with open(queries_filepath, 'r', encoding='utf8') as f:
    for line in f:
        qid, query = line.strip().split("\t")
        queries[qid] = query.strip()

### Read the train passages entities, store in passages_entities dict
passages_entities = {}
passages_entities_filepath = os.path.join(data_folder, 'entities', 'docs_entities.tsv')
with open(passages_entities_filepath, 'r', encoding='utf8') as fIn:
    print('Loading passages entities...')
    for line in fIn:
        pid, entities = line.strip().split("\t")
        passages_entities[pid] = eval(entities)

### Read the train queries entities, store in queries_entities dict
queries_entities = {}
queries_entities_filepath = os.path.join(data_folder, 'entities', 'dev_small_queries_entities.tsv')
with open(queries_entities_filepath, 'r', encoding='utf8') as fIn:
    print('Loading queries entities...')
    for line in fIn:
        qid, entities = line.strip().split("\t")
        queries_entities[qid] = eval(entities)

print('Loading qrels...')
qrels = {}
if LOCAL:
    qrels_filepath = os.path.join(data_folder, 'runbm25anserini.dev')
else:
    qrels_filepath = os.path.join(data_folder, 'runbm25anserini_notnull.dev')
with open(qrels_filepath, 'r', encoding='utf8') as f:
    for line in f:
        qrel = line.strip().split(" ")
        qid = qrel[0]
        pid = qrel[2]
        if qid in qrels:
            qrels[qid].append(pid)
        else:
            qrels[qid] = [pid]

# Search in a loop for the individual queries
ranks = {}
cnt = 0
for qid, passages in tqdm(qrels.items()):
    query = queries[qid]
    query_entity_spans = [(entity['start'], entity['end']) for entity in queries_entities[qid]]
    query_entities = [entity.get('title', 'spot') for entity in queries_entities[qid]]

    collection_entity_spans = {}
    collection_entities = {}
    for pid in passages:
        if pid in collection_entity_spans:
            collection_entity_spans[pid].append([(entity['start'], entity['end']) for entity in passages_entities[pid]])
        else:
            collection_entity_spans[pid] = [(entity['start'], entity['end']) for entity in passages_entities[pid]]
        if pid in collection_entities:
            collection_entities[pid].append([entity.get('title', 'spot') for entity in passages_entities[pid]])
        else:
            collection_entities[pid] = [entity.get('title', 'spot') for entity in passages_entities[pid]]

    # Concatenate the query and all passages and predict the scores for the pairs [query, passage]
    model_inputs = [[[query, collection[pid]], [query_entity_spans, collection_entity_spans[pid]],
                     [query_entities, collection_entities[pid]]] for pid in passages]
    scores = model.predict(model_inputs)

    # Sort the scores in decreasing order
    results = [{'pid': pid, 'score': score} for pid, score in zip(passages, scores)]
    results = sorted(results, key=lambda x: x['score'], reverse=True)

    ranks[qid] = results

print('Writing the result to file...')
with open(run_output_path, 'w', encoding='utf-8') as out:
    for qid, results in ranks.items():
        for rank, hit in enumerate(results):
            out.write(f'{qid} Q0 {hit["pid"]} {rank + 1} {hit["score"]} CrossEncoder\n')

print('Evaluation...')
qrels = ir_datasets.load('msmarco-passage/dev/small').qrels_iter()
run = ir_measures.read_trec_run(run_output_path)
print(ir_measures.calc_aggregate([nDCG@10, P@10, AP@10, RR@10, R@10], qrels, run))
