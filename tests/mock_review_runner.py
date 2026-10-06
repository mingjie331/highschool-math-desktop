"""Deterministic review data; reuses the test-only DeepSeek transport."""
import io
import json
from tests.mock_agent_runner import agent
from backend.runner import main


def seed():
    from backend.runtime import initialize_seed
    initialize_seed();agent.db.initialize()
    from contextlib import closing
    with closing(agent.db.connect()) as conn:
        if conn.execute('SELECT 1 FROM ai_tasks').fetchone():return
    from PIL import Image,ImageDraw,ImageFont
    image=Image.new('RGB',(600,850),'white');draw=ImageDraw.Draw(image);font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',22)
    draw.text((30,25),'19. 已知 1+1，求结果。',font=font,fill='black');draw.text((30,110),'答案：2；解析：由加法得 1+1=2。',font=font,fill='black')
    draw.rectangle((80,250,480,530),outline='black',width=2);out=io.BytesIO();image.save(out,'PNG')
    sessions=[agent.create_session('第一套材料'),agent.create_session('第二套材料')]
    for n,session in enumerate(sessions):
        attachment=agent.attach(session['id'],f'材料{n+1}.png',out.getvalue())
        task=agent.create_task(session['id'],{'attachment_ids':[attachment['id']],'instruction':'隔离核对测试','source_title':f'核对测试卷{n+1}'})
        form={'type':'fill','question_tex':f'第{n+1}套计算 $1+1$。','answer_tex':'2','solution_tex':'由加法得 $1+1=2$。',
              'collection_code':'gaoyi-first','point_code':'1.1','original_number':'19','answer_origin':'original','solution_origin':'original',
              'regions':[{'image_id':attachment['id'],'rect':[0,0,1,1]}]}
        agent.accept_candidates(task['id'],[form])
        if n==1:
            agent.accept_candidates(task['id'],[{**form,'type':'single','question_tex':'求 $2+2$。','options':['$1$','$2$','$3$','$4$'],
                'answer_tex':'D','solution_tex':'$2+2=4$。','original_number':'20','classification_uncertain':True,'answer_conflict':True}])
            figure_item=agent.accept_candidates(task['id'],[{**form,'type':'multi','question_tex':'选择偶数。[FIGURE:fig2]','options':['$1$','$2$','$3$','$4$'],
                'answer_tex':'BD','solution_tex':'偶数为 $2,4$。','original_number':'21',
                'figures':[{'image_id':attachment['id'],'rect':[80/600,250/850,480/600,530/850],'id':'fig2','field':'question_tex'}]}])[0]
            current=agent.get_item(figure_item)
            current=agent.crop_figure(figure_item,current['revision'],{'image_id':attachment['id'],'rect':[80/600,250/850,480/600,530/850]},'question_tex','fig2')
            assert current['details']['figure_issues']
            # Reproduce the old contradictory state: checkbox checked, edge warning unresolved.
            details=current['details'];details.update(figures_confirmed=True,validation_error='配图边缘可能截断，请先调整标记配图的裁剪范围，再确认完整性')
            agent._set_item(figure_item,'needs_review',details)
            agent.accept_candidates(task['id'],[{**form,'type':'long','question_tex':'（1）求 $x$；\n（2）求 $y$。','answer_tex':'2,3',
                'solution_tex':'（1）$x=2$。\n（2）$y=3$。','original_number':'22'}])
    import os
    if os.environ.get('QD_IMPORT_132')=='1':
        session=sessions[0];attachment=agent.get_session(session['id'])['attachments'][0]
        task=agent.create_task(session['id'],{'attachment_ids':[attachment['id']],'source_title':'旧失败材料'})
        iid=agent.accept_candidates(task['id'],[{'type':'long','question_tex':'','regions':[{'image_id':attachment['id'],'rect':[0,0,1,1]}]}],_allow_empty=True)[0]
        item=agent.get_item(iid);agent._set_item(iid,'needs_review',{**item['details'],'stage_error':{'stage':'recognition','code':'candidate_invalid','message':'此题题干未提取完成'}},expected=item['revision'])

seed()
if __name__=='__main__':main()
