"""Shared, conservative extraction of pasted job listings; no network or writes."""
import html
import re
import unicodedata
from urllib.parse import urlparse

MAX_TEXT = 200_000
MAX_DESCRIPTION = 60_000
LINK = re.compile(r'\[([^\]\n]+)\]\(https?://[^\n]*\)')
SALARY = re.compile(r'(?:HK\s*\$|HKD|\$|月薪|每月)\s*\d', re.I)
DESCRIPTION = {'完整職位描述', '完整职位描述', 'full job description', 'job description', 'jobs description', '工作內容', '职位描述', '職位描述'}
RESP = {'responsibilities', 'key responsibilities', 'job responsibilities', 'job duties', 'duties', 'what you will do', 'what you’ll do', 'what you will be doing', '工作職責', '工作內容', '職責'}
REQ = {'requirements', 'job requirements', 'qualifications', 'what you will need', 'what you need', '任職要求', '職位要求', '資格'}
OTHER = {'benefits', 'fringe benefits', 'how to apply', 'nice to have', 'what we offer', 'company overview', '公司概覽', '福利', '待遇', '技能', 'skills', 'more information', '更多資料', 'location', 'work location', '工作地點', 'shift', 'scheduled weekly hours', 'worker type', 'employment type', 'employee type', '工種', 'd&i statement', 'education', 'experience', 'application question(s)'}
APPLY = {'立即申請', '立即申请', '立即應徵', '透過公司網站應徵', '透過公司網站申請', '通过公司网站申请', '在公司網站申請', 'apply now', 'apply on company site', 'apply on company website', 'apply on employer site', 'apply on employer website'}
MISSING_PAY = {'未提供薪酬資料', '未提供薪資', '薪酬資料未提供', 'salary not provided', 'pay not provided'}
FOOTERS = ('our office is at ', 'major stops of company coach', 'personal data collected', 'talent acquisition based on ', 'interested parties ', 'interested applicants ', 'where appropriate, applicants ', 'hkex is committed as an equal opportunity employer', 'a three-year employment contract ', 'remuneration will ', 'we offer attractive ', 'fringe benefits to ')

def visible(value):
    return LINK.sub(lambda match: match.group(1), html.unescape(value))

def key(value):
    value = unicodedata.normalize('NFKC', visible(value)).casefold()
    value = re.sub(r'^[\s•·✓✔*\-–—]+', '', value)
    return ' '.join(value.split()).rstrip(' :;：；.。')

def normalize_paste(value):
    return [visible(line).strip() for line in value.splitlines() if visible(line).strip()]

def is_salary(value):
    return bool(SALARY.search(unicodedata.normalize('NFKC', value)))

def is_location(value):
    return bool(re.search(r'hong kong|kowloon|new territories|香港|九龍|新界', value, re.I)) and not bool(re.search(r'\b(?:limited|ltd|company|solutions)\b', value, re.I))

def valid_identity(value):
    k = key(value)
    return (bool(k) and len(value) <= 200 and not is_salary(value)
            and not re.fullmatch(r'\d(?:\.\d)?(?: out of 5(?: stars)?)?', k)
            and k not in DESCRIPTION | RESP | REQ | OTHER | APPLY
            and not k.startswith(('http://', 'https://', 'job ref', 'posted on')))

def split_sections(description):
    parts = {'responsibilities': [], 'requirements': []}
    current = None
    for line in (description or '').splitlines():
        k = key(line)
        label = k.split(':', 1)[0].strip()
        if k in RESP:
            current = 'responsibilities'
        elif k in REQ:
            current = 'requirements'
        elif (k in OTHER or label in OTHER or k.startswith(FOOTERS)
              or k.startswith(('job types:', 'pay:'))):
            current = None
        elif k in DESCRIPTION:
            continue
        elif current:
            parts[current].append(line)
    return {name: '\n'.join(lines).strip()[:20000] or None for name, lines in parts.items()}

def source_hint(text, source_url=None):
    signals = set()
    for url in re.findall(r'https?://[^\s\)"<>]+', text) + ([source_url] if source_url else []):
        host = (urlparse(url).hostname or '').casefold()
        for domain, name in [('indeed.com', 'Indeed'), ('ctgoodjobs.hk', 'CTgoodjobs'), ('jobsdb.com', 'JobsDB')]:
            if host == domain or host.endswith('.' + domain):
                signals.add(name)
    if re.search(r'\bvia\s+ctgoodjobs\b', text, re.I):
        signals.add('CTgoodjobs')
    return next(iter(signals)) if len(signals) == 1 else None

def build_paste_preview(text, source_url=None):
    if not text.strip():
        raise ValueError('Please paste some job text.')
    if len(text) > MAX_TEXT:
        raise ValueError('Pasted text exceeded the size limit.')
    records = [(line, visible(line).strip(), key(line)) for line in text.splitlines() if key(line)]
    names = [row[1] for row in records]
    keys = [row[2] for row in records]
    anchors = []
    for i, k in enumerate(keys):
        if k not in DESCRIPTION:
            continue
        if i and keys[i - 1] in DESCRIPTION:
            continue
        # A heading within an existing body is not a new listing without a new header.
        lower = max(anchors[-1]['start'] if anchors else 0, i - 60)
        apply = next((j for j in range(i - 1, lower - 1, -1) if keys[j] in APPLY), None)
        overview = i + 1 < len(keys) and keys[i + 1] == 'company overview'
        title = company = location = None
        metadata = []
        kind = None
        if overview or k == '工作內容':
            kind = 'CTgoodjobs'
            stop = apply if apply is not None and apply >= i - 5 else i
            if stop >= 2 and all(valid_identity(s) for s in names[stop - 2:stop]):
                title, company = names[stop - 2:stop]
        elif apply is not None:
            kind = 'Indeed'
            # Choose identity next to the selected listing, never metadata from recommendations.
            context = [j for j in range(max(lower, apply - 30), apply)
                       if not re.fullmatch(r'\d(?:\.\d)?(?: out of 5(?: stars)?)?', keys[j])]
            loc_pos = next((p for p in range(len(context) - 1, -1, -1)
                            if is_location(names[context[p]]) and not is_salary(names[context[p]])), None)
            if loc_pos is not None:
                loc = context[loc_pos]
                location = names[loc]
                if loc_pos >= 2:
                    pair = [names[context[loc_pos - 2]], names[context[loc_pos - 1]]]
                    if all(valid_identity(s) and not is_location(s) for s in pair):
                        title, company = pair
                tail = names[loc + 1:apply]
                if any(re.search(r'\b(?:limited|ltd|gmbh|corporation)\b', s, re.I) for s in tail):
                    title = company = None
                metadata = names[apply + 1:i]
                if title and company:
                    metadata = names[loc + 1:apply] + metadata
                origin = next((s[3:].strip() for s in names[apply + 1:i] if s.startswith('來源於')), None)
                if origin and key(origin) != key(location):
                    title = company = None
                    location = origin[:200]
                    metadata = names[apply + 1:i]
                # Unknown labels are tolerated, but suspicious multi-card tails trigger manual review.
                if sum(is_location(s) for s in names[loc + 1:apply]) > 0:
                    title = company = None
            else:
                metadata = names[apply + 1:i]
        else:
            continue
        if anchors and apply is None and not overview and k != '工作內容':
            continue
        anchors.append({'start': i, 'title': title, 'company': company, 'location': location,
                        'metadata': metadata, 'kind': kind})
    if not anchors and 'employer site' in keys and any(k.startswith('report this job') for k in keys):
        pos = keys.index('employer site')
        body_start = next((i for i in range(pos + 3, len(keys)) if keys[i] in RESP | REQ), None)
        pair = names[pos + 1:pos + 3]
        if body_start is not None and len(pair) == 2 and all(valid_identity(s) for s in pair):
            metadata = names[pos + 3:body_start]
            location = next((s for s in metadata if is_location(s) and not is_salary(s)), None)
            anchors.append(dict(start=body_start - 1, title=pair[0], company=pair[1],
                                location=location, metadata=metadata, kind='JobsDB'))
    warnings = ['請核對辨識結果；儲存前可修改資料。 / Review and edit the extracted details before saving.']
    ambiguous = len(anchors) > 1
    chosen = anchors[0] if anchors and not ambiguous else None
    title = chosen['title'] if chosen else None
    company = chosen['company'] if chosen else None
    if title == company:
        title = None
    location = chosen['location'] if chosen else None
    hint = source_hint(text, source_url)
    kind = chosen['kind'] if chosen else None
    source = hint or kind
    if hint and kind and hint != kind:
        source = None
        warnings.append('來源線索不一致，請確認。 / Conflicting source hints; please check.')
    start = chosen['start'] + 1 if chosen else 0
    while start < len(keys) and keys[start] in DESCRIPTION | {'company overview'}:
        start += 1
    end = len(records)
    if chosen:
        end = next((i for i in range(start, len(keys)) if keys[i].startswith(('舉報職位', '举报职位', 'report job', 'report this job', '職場攻略'))), end)
    description = '\n'.join(row[0] for row in records[start:end]) if chosen else text
    metadata = chosen['metadata'] if chosen else []
    salary = None
    if chosen and not any(key(s) in MISSING_PAY for s in metadata):
        pay_lines = [s for s in metadata if is_salary(s)]
        if not pay_lines:
            pay_lines = [row[1] for row in records[start:end] if re.match(r'^(?:pay|salary|月薪|薪酬|薪資)\s*[:：]?', row[1], re.I) and is_salary(row[1])]
        if len(set(pay_lines)) == 1:
            salary = pay_lines[0][:200]
        elif len(set(pay_lines)) > 1:
            warnings.append('找到多個薪資值，請確認。 / Multiple salary values; please check.')
    if chosen and not location:
        for i in range(chosen['start'] + 1, start):
            if keys[i].startswith('來源於'):
                location = names[i][3:].strip()[:200] or None
        for i in range(start, end):
            if keys[i] in {'工作地點', 'location', 'work location'} and i + 1 < end:
                if is_location(names[i + 1]):
                    location = names[i + 1][:200]
                break
    if ambiguous:
        source = hint
        warnings.append('可能含多份職位；已保留原文，請只保留一份或手動填寫。 / Multiple listings detected; select one or fill in details manually.')
    if not chosen or not title or not company:
        warnings.append('已保留文字，請補填職位及公司。 / Text retained; please complete the title and company.')
    if len(description) > MAX_DESCRIPTION:
        warnings.append('描述超過儲存上限，只保留前 60,000 字元；完整貼文在 raw_text。 / Description truncated to 60,000 characters; full paste is in raw_text.')
    sections = split_sections(description) if chosen else {'responsibilities': None, 'requirements': None}
    job = dict(title=title, company=company, url=source_url, location=location, salary=salary,
               source=source, status='saved', notes=None, applied_at=None, posted_at=None,
               apply_by=None, description=description[:MAX_DESCRIPTION], cover_letter=None, **sections)
    missing = [name for name in ('title', 'company') if not job[name]]
    return dict(result='partial' if missing else 'ready', job=job, source_job_id=None,
                extraction_method='paste_text', missing_required=missing,
                missing_optional=[name for name in ('location', 'salary') if not job[name]],
                can_save=not missing, warnings=warnings, saved=False, raw_text=text)
