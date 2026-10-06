"""Opt-in render inspection of isolated copies; no model or credential access."""
import hashlib,json,os,shutil,sqlite3,sys,tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUTPUT=ROOT/'test-results/render-132';OUTPUT.mkdir(parents=True,exist_ok=True)
HOME=Path(tempfile.mkdtemp(dir=OUTPUT,prefix='run-'))
from tests.private_paths import DATA
SOURCE=Path(sys.argv[1]).resolve() if len(sys.argv)>1 and not sys.argv[1].startswith('--') else DATA
if SOURCE is None:raise SystemExit('Provide --data or QD_TEST_DATA; no automatic use of personal release data')
original=hashlib.sha256((SOURCE/'question_bank.sqlite3').read_bytes()).hexdigest()
os.environ.update(QD_HOME=str(HOME),QD_RESOURCES=str(ROOT/'resources'))
(HOME/'data').mkdir();shutil.copytree(SOURCE/'assets',HOME/'data/assets')
with sqlite3.connect((SOURCE/'question_bank.sqlite3').as_uri()+'?mode=ro',uri=True) as a,sqlite3.connect(HOME/'data/question_bank.sqlite3') as b:a.backup(b)
from backend.catalog import CatalogDB
from backend import latex_service
from backend.tex_layout import subpart_paragraphs
import pypdfium2 as pdfium
db=CatalogDB(HOME/'data/question_bank.sqlite3');db.initialize()
questions=db.ordered_snapshot('gaoyi-first')[1]
question=next((q for code in __import__('backend.catalog',fromlist=['COLLECTION_MAP']).COLLECTION_MAP for q in db.ordered_snapshot(code)[1] if q['type']=='long' and any(o.get('title')=='月考卷' for o in q['sources'].get('origins',[]))),None)
if question is None:
    with db.connect() as c:
        row=c.execute("SELECT content_json FROM drafts WHERE json_extract(content_json,'$.form.type')='long' AND length(json_extract(content_json,'$.form.question_tex'))>100 LIMIT 1").fetchone()
        if row:question=json.loads(row[0])['form']
assert question,'Provide material with the actual long question'
cases=[('actual-19',question),('subpart-example',{'type':'long','question_tex':'已知有限集合 $A$。（1）求 $m$ 的值；（2）证明至少有一个元素大于2；（3）讨论是否存在。','answer_tex':'（1）$m=2$；（2）成立；（3）存在。','solution_tex':'（1）由条件得 $m=2$。 （2）假设所有元素不大于2，得到矛盾。 （3）取 $A=\\{2,3\\}$，满足要求。','options':[],'sources':{}})]
checks=[]
for name,form in cases:
    for solutions in [False,True]:
        view='solution' if solutions else 'question';source=latex_service.single_document(form,solutions)
        output=OUTPUT/f'{name}-{view}.pdf';output.write_bytes(latex_service.compile_tex(source,'layout-132'))
        document=pdfium.PdfDocument(output);labels=[]
        for index in range(len(document)):
            page=document[index];text=page.get_textpage();content=text.get_text_range()
            import re
            # Record exact positions of parenthesized subpart labels for visual QA.
            for match in re.finditer(r'[（(]\s*([123])\s*[）)]',content):
                rects=[text.get_charbox(i) for i in range(match.start(),min(match.end(),text.count_chars()))]
                labels.append({'number':match[1],'page':index+1,'x':min(r[0] for r in rects),'y':min(r[1] for r in rects)})
            bitmap=page.render(scale=1.4);bitmap.to_pil().save(OUTPUT/f'{name}-{view}-{index+1}.png');bitmap.close();text.close();page.close()
        document.close();assert len(labels)>=3,(name,view,labels)
        # Each successive marker in the same answer/stem sequence must have a new line.
        for a,b in zip(labels,labels[1:]):
            if int(b['number'])==int(a['number'])+1 and a['page']==b['page']:assert abs(a['y']-b['y'])>5,(a,b)
        checks.append({'name':name+'-'+view,'passed':True,'labels':labels,'png_pages':len(list(OUTPUT.glob(f'{name}-{view}-*.png')))})
assert hashlib.sha256((SOURCE/'question_bank.sqlite3').read_bytes()).hexdigest()==original
(OUTPUT/'results.json').write_text(json.dumps({'remote_calls':0,'original_database_unchanged':True,'checks':checks},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'checks':checks},ensure_ascii=False))
