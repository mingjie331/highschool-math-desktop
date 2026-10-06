"""Local-only UI fixture; no network recognition of the private PDF."""
from pathlib import Path
import io
from tests.mock_review_runner import agent
from backend.runner import main


def seed_material():
    if any(s['title']=='滚动验收' for s in agent.sessions()):return
    root=Path(__file__).resolve().parents[1]
    session=agent.create_session('滚动验收')
    pdf=next(__import__('tests.private_paths',fromlist=['MATERIALS']).MATERIALS.glob('*四川百师联盟*.pdf'),None)
    if pdf:
        document=agent.attach(session['id'],pdf.name,pdf.read_bytes());page=document['pages'][1]
    else:
        from PIL import Image,ImageDraw
        image=Image.new('RGB',(700,2200),'white');draw=ImageDraw.Draw(image)
        for y in range(0,2200,100):draw.text((20,y),str(y),fill='black')
        out=io.BytesIO();image.save(out,'PNG');page=agent.attach(session['id'],'长图测试.png',out.getvalue())
    rect=[.5,0,1,1] if page['width']>page['height']*1.2 else [0,0,1,1]
    task=agent.create_task(session['id'],{'attachment_ids':[page['id']],'instruction':'原材料滚动检查'})
    agent.accept_candidates(task['id'],[{'type':'long','original_number':'19','question_tex':'已知函数 $f(x)$。（1）求值；（2）证明；（3）讨论。','answer_tex':'（1）1；（2）成立；（3）存在。','solution_tex':'（1）代入求值；（2）由条件可证；（3）存在。','collection_code':'gaoyi-first','point_code':'1.1','regions':[{'image_id':page['id'],'rect':rect}]}])


seed_material()
if __name__=='__main__':main()
