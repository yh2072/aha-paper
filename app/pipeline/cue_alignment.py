"""Source clauses aligned to the word timestamps returned by the actual narration."""
from difflib import SequenceMatcher
import re

VERSION='word-clause-v3'

def normalize(text):return ''.join(c for c in text if c.isalnum()).lower()

def units(text):
    # Split a change of referenced panel even inside one grammatical sentence.
    return [s for s in re.split(r'(?<=[。！？!?；;])|(?<=[，,：:])(?=(?:子图|图[a-kA-K]|再看|接着看|随后|左侧|右侧|左上|右上|下方|上方))',text.strip()) if s.strip()]

def align(parts,events,total):
    source=normalize(''.join(parts));spoken='';owners=[]
    for event in events:
        word=normalize(event['text']);spoken+=word;owners.extend([float(event['start'])]*len(word))
    mapping={}
    for block in SequenceMatcher(None,source,spoken,autojunk=False).get_matching_blocks():
        for i in range(block.size):mapping[block.a+i]=owners[block.b+i]
    coverage=len(mapping)/max(len(source),1)
    if coverage<.8:raise ValueError(f'旁白词时间戳覆盖不足：{coverage:.1%}')
    starts=[];offset=0
    for part in parts:
        length=len(normalize(part))
        times=[mapping[i]for i in range(offset,offset+length)if i in mapping]
        if not times:raise ValueError('有讲解片段无法对应到实际词时间戳')
        starts.append(min(times));offset+=length
    if starts:starts[0]=0.0
    cues=[]
    for i,part in enumerate(parts):
        start=starts[i];end=starts[i+1] if i+1<len(parts) else total
        if end<=start:raise ValueError('旁白子句时间边界重复或倒序')
        cues.append({'text':part,'start':round(start,4),'end':round(end,4),'region':None})
    return cues,{'version':VERSION,'coverage':round(coverage,5),'words':len(events)}
