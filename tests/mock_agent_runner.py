"""Test-only transport, never copied into the packaged backend."""
import argparse
import asyncio
import json
import os
import httpx

parser=argparse.ArgumentParser();parser.add_argument('--home');parser.add_argument('--resources');parser.add_argument('--frontend')
args,_=parser.parse_known_args()
os.environ.update(QD_HOME=args.home,QD_RESOURCES=args.resources,QD_FRONTEND=args.frontend)
from backend.app import agent

async def handle(request):
    body=json.loads(request.content);messages=body['messages'];system=messages[0]['content']
    if body.get('tools'):
        outputs=[message for message in messages if message.get('role')=='tool']
        if not outputs:
            message={'content':None,'tool_calls':[{'id':'read-1','type':'function','function':{'name':'read_items','arguments':'{}'}}]}
        elif len(outputs)==1:
            data=json.loads(outputs[0]['content'])['result'];item=next(value for value in data if value['number']==2)
            message={'content':None,'tool_calls':[{'id':'update-1','type':'function','function':{'name':'update_candidate','arguments':json.dumps({'item_id':item['id'],'revision':item['revision'],'changes':{'form':{'collection_code':'gaoyi-second','point_code':'6.1'},'classification_reason':'按用户对话要求调整分类'}})}}]}
        else:message={'content':'候选题2的分类已修改，仍是草稿；请重新校验并确认入库。'}
    elif '只建立' in system:
        message={'content':json.dumps({'segments':[
            {'number':'1','role':'question','regions':[{'image_id':'view-1','rect':[0,0,1,.55]}],
             'figures':[{'id':'venn','field':'question_tex','image_id':'view-1','rect':[.08,.12,.88,.48]}]},
            {'number':'2','role':'question','regions':[{'image_id':'view-1','rect':[0,.55,1,1]}],'figures':[]}]})}
    elif 'schema=' in system:
        await asyncio.sleep(.3)
        value={'questions':[
            {'type':'fill','question_tex':r'已知集合 $A=\{1,2\}$，$B=\{2,3\}$，求 $A\cap B$。[FIGURE:venn]',
             'options':[],'answer_tex':'','solution_tex':'','collection_code':'gaoyi-first','point_code':'1.1',
             'classification_reason':'集合交集运算','original_number':'1','regions':[{'image_id':'view-1','rect':[0,0,1,.55]}],
             'figures':[{'id':'venn','field':'question_tex','image_id':'view-1','rect':[.08,.12,.88,.48]}]},
            {'type':'long','question_tex':r'解不等式 $x^2-1>0$。','options':[],'answer_tex':'','solution_tex':'',
             'collection_code':'gaoyi-first','point_code':'2.2','classification_reason':'一元二次不等式',
             'original_number':'2','regions':[{'image_id':'view-1','rect':[0,.55,1,1]}],'figures':[]},
        ]};message={'content':json.dumps(value,ensure_ascii=False)}
    elif '解析助手' in system:
        await asyncio.sleep(.1)
        question=json.loads(messages[-1]['content'][0]['text'])['question']
        if '集合' in question['question_tex']:answer=r'$\{2\}$';solution=r'交集保留两集合共有的元素，故 $A\cap B=\{2\}$。'
        else:answer=r'$(-\infty,-1)\cup(1,+\infty)$';solution=r'因式分解得 $(x-1)(x+1)>0$，因此 $x<-1$ 或 $x>1$。'
        message={'content':json.dumps({'answer_tex':answer,'solution_tex':solution,'answer_conflict':False,'uncertainties':[]},ensure_ascii=False)}
    else:message={'content':'{"ok":true}'}
    return httpx.Response(200,json={'choices':[{'message':message,'finish_reason':'stop'}],'model':'mock-deepseek-for-tests',
        'usage':{'prompt_tokens':100,'completion_tokens':40,'total_tokens':140,'prompt_cache_hit_tokens':0}})

agent.provider.transport=httpx.MockTransport(handle)
from backend.runner import main
if __name__=='__main__':main()
