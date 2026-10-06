import asyncio
import json
import threading
import unittest
import httpx
from backend.deepseek import DeepSeekProvider,ProviderError,AgentCancelled


class ProviderTests(unittest.TestCase):
    def test_budget_reserves_concurrent_requests_and_unknown_retry_bills(self):
        from backend.deepseek import ReferenceBudget
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            budget=ReferenceBudget(Path(directory)/'budget.json',1)
            budget.reserve(.6)
            with self.assertRaises(ProviderError):budget.reserve(.6)
            budget.settle(.6,.1);budget.reserve(.6);budget.settle(.6)
            self.assertAlmostEqual(budget.spent,.7)
            with self.assertRaises(ProviderError):budget.reserve(.4)
            self.assertAlmostEqual(ReferenceBudget(budget.path,1).spent,.7)

    def test_low_effort_and_truncated_error_metadata(self):
        bodies=[]
        def handle(request):
            bodies.append(json.loads(request.content))
            return httpx.Response(200,json={'choices':[{'message':{'content':''},'finish_reason':'length'}],'usage':{'completion_tokens':32000}})
        provider=DeepSeekProvider(transport=httpx.MockTransport(handle));provider.configure('key')
        with self.assertRaises(ProviderError) as error:asyncio.run(provider.json([{'role':'user','content':'json'}],thinking=True,reasoning_effort='low',max_tokens=32000))
        self.assertEqual(bodies[0]['reasoning_effort'],'low');self.assertEqual(error.exception.detail('completion')['max_tokens'],32000)
        self.assertEqual(error.exception.code,'output_truncated')
    def test_json_payload_vision_and_usage(self):
        requests=[];usage=[]
        def handle(request):
            body=json.loads(request.content);requests.append(body)
            self.assertEqual(request.headers['authorization'],'Bearer test-key')
            return httpx.Response(200,json={'choices':[{'message':{'content':'{"ok":true}'},'finish_reason':'stop'}],
                'usage':{'prompt_tokens':15,'completion_tokens':3,'total_tokens':18},'model':'deepseek-flash'})
        provider=DeepSeekProvider(transport=httpx.MockTransport(handle));provider.configure('test-key')
        value,_=asyncio.run(provider.json([{'role':'system','content':'json'},{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,AA=='}}]}],usage_callback=usage.append))
        self.assertEqual(value,{'ok':True})
        self.assertEqual(requests[0]['thinking'],{'type':'disabled'})
        self.assertEqual(requests[0]['response_format'],{'type':'json_object'})
        self.assertEqual(usage,[None,{'prompt_tokens':15,'completion_tokens':3,'total_tokens':18}])
        self.assertNotIn('test-key',json.dumps(provider.status()))

    def test_auth_balance_and_bad_request_not_retried_or_echoed(self):
        for status in [400,401,402,403]:
            calls=[]
            def handle(request):calls.append(request);return httpx.Response(status,text='test-secret-key')
            provider=DeepSeekProvider(transport=httpx.MockTransport(handle));provider.configure('test-secret-key')
            with self.assertRaises(ProviderError) as error:asyncio.run(provider.test())
            self.assertEqual(len(calls),1);self.assertNotIn('test-secret-key',str(error.exception))

    def test_transient_errors_have_bounded_retries(self):
        calls=[]
        def handle(request):
            calls.append(request)
            return httpx.Response(503) if len(calls)<3 else httpx.Response(200,json={'choices':[{'message':{'content':'{"ok":true}'}}]})
        provider=DeepSeekProvider(transport=httpx.MockTransport(handle));provider.configure('key')
        async def immediate(*args):pass
        provider._delay=immediate
        self.assertTrue(asyncio.run(provider.test())['ok']);self.assertEqual(len(calls),3)

    def test_cancel_closes_inflight_request(self):
        signal=threading.Event();started=threading.Event();stopped=threading.Event()
        async def handle(request):
            started.set()
            try:await asyncio.sleep(30)
            finally:stopped.set()
        provider=DeepSeekProvider(transport=httpx.MockTransport(handle));provider.configure('key')
        async def scenario():
            task=asyncio.create_task(provider.json([{'role':'user','content':'json'}],cancel=signal))
            while not started.is_set():await asyncio.sleep(.01)
            signal.set()
            with self.assertRaises(AgentCancelled):await asyncio.wait_for(task,1)
        asyncio.run(scenario());self.assertTrue(stopped.is_set())

    def test_empty_truncated_or_nonobject_outputs_rejected(self):
        for content,finish in [('',None),('[]','stop'),('{"ok":true}','length')]:
            provider=DeepSeekProvider(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'choices':[{'message':{'content':content},'finish_reason':finish}]})))
            provider.configure('key')
            with self.assertRaises(ProviderError):asyncio.run(provider.test())

    def test_tools_do_not_add_json_format_or_enable_thinking(self):
        bodies=[]
        def handle(request):bodies.append(json.loads(request.content));return httpx.Response(200,json={'choices':[{'message':{'content':'完成'}}]})
        provider=DeepSeekProvider(transport=httpx.MockTransport(handle));provider.configure('key')
        asyncio.run(provider.request([{'role':'user','content':'修正'}],tools=[{'type':'function','function':{'name':'read_items','parameters':{}}}]))
        self.assertNotIn('response_format',bodies[0]);self.assertEqual(bodies[0]['thinking']['type'],'disabled')

    def test_global_remote_limit_includes_connection_tests(self):
        counts={'active':0,'maximum':0}
        async def handle(request):
            counts['active']+=1;counts['maximum']=max(counts['maximum'],counts['active'])
            await asyncio.sleep(.08);counts['active']-=1
            return httpx.Response(200,json={'choices':[{'message':{'content':'{"ok":true}'}}]})
        provider=DeepSeekProvider(transport=httpx.MockTransport(handle));provider.configure('key')
        async def run():await asyncio.gather(*(provider.test() for _ in range(5)))
        asyncio.run(run());self.assertEqual(counts['maximum'],2)
