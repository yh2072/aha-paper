"""The explainer's focus: what the reader wants understood, in their words.

Two kinds live here, and the difference is who owns them.

A *preset* ships with the app. It exists in both languages, because the chip
that offers it sits next to an interface that is already translated -- a Chinese
sentence appearing in an English composer is the bug this module was written to
remove. Presets are data, not DOM: web/i18n.js translates the interface by
looking a Chinese source string up in a dictionary, and it deliberately never
touches a value or a user-authored attribute, so a prompt could never have been
translated that way. The container that renders these carries data-no-i18n and
picks the language itself.

A *custom* prompt is the user's own sentence, saved in whatever language they
typed it. It is never translated, not even into the other interface language:
rewriting what someone wrote and handing it back as theirs would be worse than
leaving it alone.

Presets are the professional readings of a paper -- the angles a reviewer, a
replicator or a practitioner each take -- rather than a list of topics. Each one
has to stand on its own as an instruction to the writer, because that is exactly
where it ends up: deep_script sends it on as the user's focus, under the same
constraints on accuracy and sourcing as everything else.
"""
import json
import re
import time
import uuid
from pathlib import Path

from . import config

MAX_LABEL = 40
MAX_PROMPT = 2000     # the same ceiling /api/projects/{pid}/guidance enforces
MAX_CUSTOM = 50       # a bounded file, and a chip row that still reads as a row

PRESETS = [
    {
        'id': 'design',
        'label': {'zh': '研究问题与实验设计', 'en': 'Question & study design'},
        'prompt': {
            'zh': '请重点讲清研究问题、实验设计、对照条件和关键指标，用专业但通俗的语言解释。'
                  '说明样本或被试怎么来的、任务是什么、对照组和实验组差在哪一个变量上。',
            'en': 'Focus on the research question, the study design, the control conditions and the '
                  'key metrics, in language that is technical but readable. Say where the sample or '
                  'the participants came from, what the task was, and which single variable '
                  'separates the control condition from the experimental one.',
        },
    },
    {
        'id': 'figures',
        'label': {'zh': '带我读懂论文主图', 'en': 'Walk me through the figures'},
        'prompt': {
            'zh': '请深入解读关键主图，逐个面板解释坐标、比较、结果与证据边界，配合光标和智能缩放。'
                  '先讲这张图的整体结构，再进到子图，最后说明它到底支持了什么结论。',
            'en': 'Read the key figures closely, panel by panel: the axes, the comparison being '
                  'made, the result, and the limits of what it shows. Start from the figure\'s '
                  'overall structure, then go into the subpanels, then say what conclusion it '
                  'actually supports. Use the cursor and the zoom to point as you go.',
        },
    },
    {
        'id': 'limits',
        'label': {'zh': '方法、结果与局限', 'en': 'Method, results & limits'},
        'prompt': {
            'zh': '请重点比较新方法与基线，解释定量结果、局限和实际应用边界，不夸大结论。'
                  '把「作者证明了什么」和「作者只是观察到什么」分开说。',
            'en': 'Compare the new method against its baselines, explain the quantitative results, '
                  'the limitations and the boundary of practical application, and do not overstate '
                  'the conclusion. Keep what the authors demonstrated separate from what they '
                  'merely observed.',
        },
    },
    {
        'id': 'statistics',
        'label': {'zh': '统计与效应量', 'en': 'Statistics & effect sizes'},
        'prompt': {
            'zh': '请讲清统计部分：用了什么检验、样本量和检验力、效应量有多大、置信区间多宽、'
                  '有没有做多重比较校正。区分「统计显著」和「值得在意」，并指出 p 值撑不起的说法。',
            'en': 'Explain the statistics properly: which tests were used, the sample size and the '
                  'power, how large the effect actually is, how wide the confidence intervals are, '
                  'and whether multiple comparisons were corrected for. Separate "statistically '
                  'significant" from "worth caring about", and name any claim the p-values cannot '
                  'carry.',
        },
    },
    {
        'id': 'reproducibility',
        'label': {'zh': '可复现性：数据与代码', 'en': 'Reproducibility: data & code'},
        'prompt': {
            'zh': '请从复现的角度讲这篇论文：数据怎么拿、预处理有哪些步骤、超参数和随机种子说清了吗、'
                  '代码和权重是否公开、算力规模多大。指出哪些细节缺失会让别人复现不出来。',
            'en': 'Explain this paper from the point of view of someone trying to reproduce it: how '
                  'to obtain the data, what the preprocessing steps are, whether the '
                  'hyperparameters and random seeds are stated, whether code and weights are '
                  'released, and the scale of compute involved. Name the missing details that would '
                  'stop a reproduction from working.',
        },
    },
    {
        'id': 'contribution',
        'label': {'zh': '它到底新在哪', 'en': 'What is actually new here'},
        'prompt': {
            'zh': '请把这篇论文放回它的相关工作里：前人做到哪一步、这篇的新东西具体是哪一个部件或哪一个观察、'
                  '去掉它结果会怎样。不要把「组合了已有方法」说成「提出了新范式」。',
            'en': 'Place this paper back in its related work: how far prior work had got, which '
                  'specific component or observation is new here, and what the result would look '
                  'like without it. Do not describe a combination of existing methods as a new '
                  'paradigm.',
        },
    },
    {
        'id': 'reviewer',
        'label': {'zh': '审稿人视角', 'en': "A reviewer's read"},
        'prompt': {
            'zh': '请像认真的审稿人那样读这篇论文：证据链最薄弱的一环在哪、哪些结论超出了数据支持范围、'
                  '缺了哪个对照或消融实验、有没有替代解释没被排除。保持公允，不为了挑错而挑错。',
            'en': 'Read this paper as a careful reviewer would: the weakest link in the chain of '
                  'evidence, the conclusions that reach past what the data support, the missing '
                  'control or ablation, and the alternative explanations that were not ruled out. '
                  'Be fair rather than adversarial.',
        },
    },
    {
        'id': 'transfer',
        'label': {'zh': '能不能用在我的场景', 'en': 'Can I use this'},
        'prompt': {
            'zh': '请讲这项研究能迁移到什么场景、在什么条件下会失效、要用它需要什么前提数据或算力。'
                  '明确区分论文直接支持的用法、合理但未验证的用法，以及不能推断的用法。',
            'en': 'Explain where this work transfers, the conditions under which it would fail, and '
                  'what data or compute a practitioner would need to apply it. Separate clearly: '
                  'the uses the paper directly supports, the uses that are plausible but untested, '
                  'and the uses that cannot be inferred from it at all.',
        },
    },
]

_IDS = {p['id'] for p in PRESETS}


def _store() -> Path:
    """Beside .env and data/, because it is the same kind of thing: the user's
    own state, which belongs to this machine rather than to the repository."""
    return config.STATE_DIR / 'prompts.json'


def _read() -> list[dict]:
    path = _store()
    if not path.exists():
        return []
    try:
        saved = json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        # A corrupt file must not take the home page down with it. The prompts
        # are a convenience; losing them is recoverable, a blank app is not.
        return []
    items = saved.get('prompts') if isinstance(saved, dict) else saved
    return [p for p in (items or []) if isinstance(p, dict) and p.get('id') and p.get('prompt')]


def _write(items: list[dict]) -> None:
    path = _store()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps({'version': 1, 'prompts': items},
                                    ensure_ascii=False, indent=1), encoding='utf-8')
    temporary.replace(path)       # replace, so a crash mid-write cannot truncate the real file


def _clean(label: str, prompt: str) -> tuple[str, str]:
    prompt = (prompt or '').strip()
    if not prompt:
        raise ValueError('请先写下讲解重点，再保存为预设')
    if len(prompt) > MAX_PROMPT:
        raise ValueError(f'讲解重点请控制在{MAX_PROMPT}字以内')
    label = re.sub(r'\s+', ' ', (label or '').strip())
    if not label:
        # Naming a prompt is work the user did not ask for. The first clause of
        # what they wrote is a better default than 'My prompt 3'.
        label = re.split(r'[。，；,;.\n]', prompt)[0][:MAX_LABEL].strip() or prompt[:MAX_LABEL]
    if len(label) > MAX_LABEL:
        label = label[:MAX_LABEL]
    if any(c in label + prompt for c in '\x00'):
        raise ValueError('内容包含无法保存的字符')
    return label, prompt


def listing(code: str) -> dict:
    """Presets in the interface's language, plus the user's own as they wrote them."""
    code = 'en' if (code or '').lower().startswith('en') else 'zh'
    return {
        'lang': code,
        'presets': [{'id': p['id'], 'kind': 'preset',
                     'label': p['label'][code], 'prompt': p['prompt'][code]}
                    for p in PRESETS],
        'custom': [{'id': p['id'], 'kind': 'custom',
                    'label': p.get('label') or p['prompt'][:MAX_LABEL],
                    'prompt': p['prompt'], 'created': p.get('created', '')}
                   for p in _read()],
        'limits': {'label': MAX_LABEL, 'prompt': MAX_PROMPT, 'custom': MAX_CUSTOM},
    }


def add(label: str, prompt: str) -> dict:
    label, prompt = _clean(label, prompt)
    items = _read()
    if len(items) >= MAX_CUSTOM:
        raise ValueError(f'自定义预设最多{MAX_CUSTOM}条，请先删掉一些')
    if any(p['prompt'].strip() == prompt for p in items):
        raise ValueError('这条讲解重点已经保存过了')
    item = {'id': 'u-' + uuid.uuid4().hex[:10], 'label': label, 'prompt': prompt,
            'created': time.strftime('%Y-%m-%d %H:%M')}
    _write(items + [item])
    return {**item, 'kind': 'custom'}


def update(prompt_id: str, label: str, prompt: str) -> dict:
    if prompt_id in _IDS:
        raise ValueError('内置预设不能改，可另存为自己的预设')
    label, prompt = _clean(label, prompt)
    items = _read()
    for item in items:
        if item['id'] == prompt_id:
            item.update(label=label, prompt=prompt)
            _write(items)
            return {**item, 'kind': 'custom'}
    raise KeyError(prompt_id)


def remove(prompt_id: str) -> None:
    if prompt_id in _IDS:
        raise ValueError('内置预设不能删除')
    items = _read()
    kept = [p for p in items if p['id'] != prompt_id]
    if len(kept) == len(items):
        raise KeyError(prompt_id)
    _write(kept)
