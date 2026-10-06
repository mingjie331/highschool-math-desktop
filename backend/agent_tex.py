"""Restricted math fragments for AI output; no file/macro execution primitives."""
import re
from .assets import image_references

COMMANDS = set('''frac dfrac tfrac sqrt overline underline vec overrightarrow overleftarrow
hat widehat bar tilde widetilde dot ddot binom dbinom tbinom substack overset underset
underbrace overbrace left right middle big Big bigg Bigg bigl bigr Bigl Bigr
sin cos tan cot sec csc arcsin arccos arctan sinh cosh tanh ln log exp lim limsup liminf
min max sup inf gcd deg det dim ker arg Pr mod bmod pmod sum prod int iint iiint oint
in notin ni subset subseteq supset supseteq cup cap bigcup bigcap emptyset varnothing
le leq leqslant ge geq geqslant ne neq equiv approx sim simeq cong propto parallel perp mid nmid
times cdot div pm mp ast circ bullet setminus smallsetminus land lor neg lnot forall exists
to mapsto rightarrow leftarrow leftrightarrow Rightarrow Leftarrow Leftrightarrow implies iff
infty partial nabla angle triangle degree alpha beta gamma delta epsilon varepsilon zeta eta
theta vartheta iota kappa lambda mu nu xi pi varpi rho varrho sigma varsigma tau upsilon phi
varphi chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega
mathbb mathcal mathrm mathbf mathit mathsf mathop bm boldsymbol text textrm textbf textit
textnormal textcircled scriptsize small normalsize displaystyle textstyle scriptstyle limits nolimits
quad qquad hspace vspace thinspace noindent par item begin end linebreak newline
ldots cdots vdots ddots dots lbrace rbrace langle rangle lvert rvert lVert rVert
lfloor rfloor lceil rceil backslash complement ensuremath includegraphics
underleftarrow underset phantom hphantom vphantom operatorname cases
linewidth textwidth textheight circlednum
because therefore boxed fbox nearrow searrow nwarrow swarrow
hline cline frown smile multicolumn multirow toprule midrule bottomrule
prime star vee wedge triangleleft triangleright oplus ominus otimes circledast
stackrel lnot vphantom hphantom mathbin mathrel mathord vert Vert top bot
'''.split())
ENVIRONMENTS = {'aligned','alignedat','gathered','gather','gather*','align','align*','equation','equation*',
    'cases','matrix','pmatrix','bmatrix','vmatrix','Vmatrix','array','enumerate','itemize','center','tabular','tabularx'}


def normalize_tex_fragment(text):
    """Scanned fill-in blanks are text rules, not TeX math subscripts."""
    parts=re.split(r'((?<!\\)\$)',text)
    math=False;output=[]
    for part in parts:
        if part=='$':math=not math
        elif not math:part=re.sub(r'(?<!\\)_{2,}',lambda m:r'\underline{\hspace{2em}}',part)
        output.append(part)
    return ''.join(output)


def question_parts(text):
    return set(re.findall(r'(?:^|\n|\s)[（(]\s*([1-9]\d?)\s*[）)]',text))


def validate_agent_tex(question: dict, allowed_assets: set[str]) -> None:
    fields = [question.get(name,'') for name in ('question_tex','answer_tex','solution_tex')]
    fields.extend(question.get('options') or [])
    for text in fields:
        if not isinstance(text,str) or len(text)>60_000:
            raise ValueError('AI 题目片段过长或格式无效')
        if '^^' in text or any(ord(c)<32 and c not in '\n\r\t' for c in text):
            raise ValueError('不允许 TeX 转义控制字符')
        # Comments must not conceal a dangerous command from the validator.
        commands=re.findall(r'\\([A-Za-z@]+|[^A-Za-z])',text)
        for command in commands:
            if len(command)>1 or command.isalpha() or command=='@':
                if command not in COMMANDS:
                    raise ValueError(f'AI LaTeX 不支持命令：\\{command}')
            elif command not in '\\{}$%_#&!,;: ()[]|':
                raise ValueError('AI LaTeX 包含不支持的控制符')
        for environment in re.findall(r'\\(?:begin|end)\s*\{([^}]+)\}',text):
            if environment not in ENVIRONMENTS:
                raise ValueError(f'AI LaTeX 不支持环境：{environment}')
        # TeX comments could join a forbidden control word across lines.
        if re.search(r'(?<!\\)%',text):
            raise ValueError('百分号请使用 \\% 表示，不接受 TeX 注释')
    if not image_references(question).issubset(allowed_assets):
        raise ValueError('配图引用不属于当前导入任务，请使用本地裁图工具')
