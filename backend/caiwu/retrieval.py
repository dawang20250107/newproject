"""知识库相关性检索（中文 BM25，字符二元组分词，零外部依赖）。

解决「知识注入取最近 N 条」的根本缺陷：知识库成长后，与当前问题相关的条目
挤不进上下文、不相关的占着窗口。此实现按当前问题做相关性召回：

- 分词：字符 bigram（中文无需词典即有良好召回）+ 英文/数字整词
- 打分：BM25（k1=1.5, b=0.75），文档=标题+内容
- 语料量级：知识库通常几百~几千条，纯 Python 内存打分毫秒级完成

后续若接入向量模型（如 SiliconFlow embedding），只需替换 rank() 内核，
调用方接口不变。
"""
import math
import re

_TOKEN_RE = re.compile(r'[a-zA-Z0-9]+')
_CJK_RE = re.compile(r'[一-鿿]')


def tokenize(text):
    """中文字符 bigram + 英文/数字整词（小写）。"""
    s = (text or '').strip()
    if not s:
        return []
    tokens = [t.lower() for t in _TOKEN_RE.findall(s)]
    cjk = _CJK_RE.findall(s)
    tokens.extend(cjk)                                   # unigram 兜底（短查询）
    tokens.extend(a + b for a, b in zip(cjk, cjk[1:]))   # bigram 主力
    return tokens


def rank(docs, query, top_k=12, min_score=0.0):
    """按 BM25 相关性排序。docs: [(id, text)]；返回 [(id, score)] 降序、截断 top_k。
    查询与语料无交集时返回空（调用方自行回退到时序）。"""
    q_tokens = tokenize(query)
    if not q_tokens or not docs:
        return []
    corpus = []
    df = {}
    for doc_id, text in docs:
        toks = tokenize(text)
        tf = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        corpus.append((doc_id, tf, len(toks)))
        for t in tf:
            df[t] = df.get(t, 0) + 1
    n = len(corpus)
    avgdl = (sum(c[2] for c in corpus) / n) if n else 0.0
    k1, b = 1.5, 0.75
    q_set = set(q_tokens)
    scored = []
    for doc_id, tf, dl in corpus:
        s = 0.0
        for t in q_set:
            f = tf.get(t)
            if not f:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            denom = f + k1 * (1 - b + b * dl / avgdl) if avgdl else f + k1
            s += idf * (f * (k1 + 1)) / denom
        if s > min_score:
            scored.append((doc_id, s))
    scored.sort(key=lambda x: -x[1])
    return scored[:top_k]
