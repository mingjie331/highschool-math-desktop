"""Render-only subquestion paragraphs. Stored mathematical text stays intact."""
import re

RENDER_VERSION = 2


def subpart_paragraphs(text):
    # Protect formulas, complete environments, macro arguments and comments.
    protected=[];math=None;env=[];depth=0;i=0;start=None
    while i<len(text):
        token=re.match(r'\\(?:begin|end)\{([^}]+)\}|\\[()[\]]|\$\$?|\\[{}$%]|[{}%]',text[i:])
        if token:
            t=token[0];was=bool(math or env or depth)
            if t.startswith(r'\begin'):env.append(token[1])
            elif t.startswith(r'\end'):
                if env:env.pop()
            elif not env:
                if t in ['$','$$',r'\(',r'\['] and not math:math=t
                elif math and t=={'$':'$','$$':'$$',r'\(':r'\)',r'\[':r'\]'}[math]:math=None
                elif not math:
                    if t=='{':depth+=1
                    elif t=='}':depth=max(0,depth-1)
                    elif t=='%':
                        end=text.find('\n',i);end=len(text) if end<0 else end
                        protected.append((i,end));i=end;continue
            now=bool(math or env or depth)
            if not was and now:start=i
            i+=len(t)
            if was and not now and start is not None:protected.append((start,i));start=None
        else:i+=1
    if start is not None:protected.append((start,len(text)))
    markers=[m for m in re.finditer(r'[（(]\s*([1-9]\d?)\s*[）)]',text) if not any(a<=m.start()<b for a,b in protected) and not re.search(r'(?:[A-Za-z]|由|见|式|根据|结合|公式|等式|条件)\s*$',text[max(0,m.start()-10):m.start()])]
    # Only ordered runs are subquestions, never an isolated numeric parenthesis.
    runs=[];run=[]
    for m in markers:
        if run and int(m[1])!=int(run[-1][1])+1:
            if len(run)>1:runs.extend(run)
            run=[]
        run.append(m)
    if len(run)>1:runs.extend(run)
    for m in reversed(runs):
        prefix=text[:m.start()]
        if re.search(r'(?:\\par|\\newline|\\linebreak|\\\\)\s*$|\n\s*\n\s*$',prefix):continue
        text=prefix+r'\par '+text[m.start():]
    return text


def has_stem(text):
    value=re.sub(r'\\includegraphics(?:\[[^\]]*\])?\{[^}]*\}|\[FIGURE:[^]]*\]', '',text)
    value=re.sub(r'\\(?:par|noindent|newline|linebreak|quad|qquad)\b|\\\\', '',value).strip(' \n\r\t{}$；;。')
    return bool(value) and not re.fullmatch(r'(?:此题)?(?:提取未完成|未识别到题干|识别失败)(?:[，,。；; ]*请重新识别)?',value)
