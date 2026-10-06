"""Official DeepSeek adapter. Credentials never enter persisted job/history data."""
import asyncio
import json
import threading
import os
from pathlib import Path
import httpx

BASE_URL='https://api.deepseek.com'
MODEL='deepseek-flash'
DEFAULT_PRICES={'input':2.0,'cached_input':0.04,'output':8.0}


class AgentCancelled(RuntimeError):
    pass


class ProviderError(RuntimeError):
    def __init__(self,message,status=0,code='provider_error',max_tokens=None,usage=None):
        super().__init__(message);self.status=status;self.code=code;self.max_tokens=max_tokens;self.usage=usage or {}

    def detail(self,stage):
        return {'stage':stage,'code':self.code,'message':str(self),'status':self.status,'max_tokens':self.max_tokens,'usage':self.usage}


class ReferenceBudget:
    """Opt-in persistent test budget; reservations include every retry and unknown bills."""
    def __init__(self,path,limit):
        self.path=Path(path);self.limit=float(limit);self.lock=threading.Lock()
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.spent=0;self.reserved=0
        if self.path.exists():
            value=json.loads(self.path.read_text('utf-8'));self.spent=value['spent']+value.get('reserved',0)
        self._save()
    def _save(self):
        temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps({'limit':self.limit,'spent':self.spent,'reserved':self.reserved}),encoding='utf-8');temp.replace(self.path)
    def reserve(self,amount):
        with self.lock:
            if self.spent+self.reserved+amount>self.limit:raise ProviderError('真实联调参考费用预算不足，已暂停后续调用',code='budget_exhausted')
            self.reserved+=amount;self._save()
    def settle(self,amount,actual=None):
        with self.lock:
            self.reserved=max(0,self.reserved-amount);self.spent+=amount if actual is None else actual;self._save()


class DeepSeekProvider:
    def __init__(self,base_url=BASE_URL,transport=None):
        self.base_url=base_url.rstrip('/')
        self.transport=transport
        self._key=''
        self._lock=threading.Lock()
        self._slots=threading.BoundedSemaphore(2)
        self.prices=dict(DEFAULT_PRICES)
        path=os.environ.get('QD_AI_TEST_BUDGET_FILE')
        self.budget=ReferenceBudget(path,os.environ.get('QD_AI_TEST_BUDGET_CNY','20')) if path else None

    def configure(self,key,prices=None):
        if not isinstance(key,str) or len(key)>512 or any(c in key for c in '\r\n') or any(not 33<=ord(c)<=126 for c in key.strip()):
            raise ValueError('API Key 格式无效')
        values=dict(DEFAULT_PRICES)
        if prices is not None:
            if not isinstance(prices,dict) or not prices.keys()<=values.keys():raise ValueError('参考价格格式无效')
            for name,price in prices.items():
                if isinstance(price,bool) or not isinstance(price,(float,int)) or not 0<=price<=10000:
                    raise ValueError('参考价格须为非负数')
                values[name]=float(price)
        with self._lock:self._key=key.strip();self.prices=values

    def status(self):
        with self._lock:
            return {'configured':bool(self._key),'base_url':BASE_URL,'model':MODEL,'prices':dict(self.prices),
                    'price_note':'每百万 token 人民币参考单价；当前默认为高峰参考价，费用以 DeepSeek 账单为准。'}

    async def request(self,messages,*,cancel=None,usage_callback=None,thinking=False,tools=None,max_tokens=12000,reasoning_effort=None):
        while not self._slots.acquire(blocking=False):
            if cancel and cancel.is_set():raise AgentCancelled('录题任务已取消')
            await asyncio.sleep(.05)
        try:return await self._request(messages,cancel=cancel,usage_callback=usage_callback,thinking=thinking,tools=tools,max_tokens=max_tokens,reasoning_effort=reasoning_effort)
        finally:self._slots.release()

    async def _request(self,messages,*,cancel=None,usage_callback=None,thinking=False,tools=None,max_tokens=12000,reasoning_effort=None):
        with self._lock:key=self._key
        if not key:raise RuntimeError('请先在设置中配置 DeepSeek API Key')
        body={'model':MODEL,'messages':messages,'max_tokens':max_tokens,
              'thinking':{'type':'enabled' if thinking else 'disabled'}}
        if thinking and reasoning_effort:body['reasoning_effort']=reasoning_effort
        if tools:body['tools']=tools
        else:body['response_format']={'type':'json_object'}
        if len(json.dumps(body,ensure_ascii=False).encode('utf-8'))>40*1024*1024:
            raise ValueError('本次图片请求过大，请按题裁剪或拆批')
        async with httpx.AsyncClient(base_url=self.base_url,transport=self.transport,
                                    timeout=httpx.Timeout(180,connect=15),follow_redirects=False) as client:
            for attempt in range(3):
                if cancel and cancel.is_set():raise AgentCancelled('录题任务已取消，草稿已保留')
                reserve=0;settled=False
                if self.budget:
                    texts=[];images=0
                    for message in messages:
                        content=message.get('content','')
                        if isinstance(content,str):texts.append(content)
                        elif isinstance(content,list):
                            for block in content:
                                if block.get('type')=='text':texts.append(block.get('text',''))
                                elif block.get('type')=='image_url':images+=1
                    reserve=((sum(map(len,texts))+2048*images+4096)*self.prices['input']+max_tokens*self.prices['output'])/1_000_000
                    self.budget.reserve(reserve)
                if usage_callback:usage_callback(None)
                call=asyncio.create_task(client.post('/chat/completions',headers={'Authorization':'Bearer '+key},json=body))
                try:
                    while not call.done():
                        if cancel and cancel.is_set():
                            call.cancel()
                            raise AgentCancelled('录题任务已取消，草稿已保留')
                        await asyncio.wait([call],timeout=.1)
                    response=await call
                except (httpx.TimeoutException,httpx.NetworkError):
                    if attempt==2:raise ProviderError('DeepSeek 连接失败或超时，可重试未完成题目') from None
                    await self._delay(attempt,cancel);continue
                finally:
                    if not call.done():call.cancel()
                    if call.cancelled() or not call.done():
                        try:await call
                        except asyncio.CancelledError:pass
                    if self.budget and (call.cancelled() or not call.done() or call.exception() is not None):
                        self.budget.settle(reserve);settled=True
                if self.budget and not settled:
                    try:
                        usage=response.json().get('usage')
                        actual=None if not usage else (usage.get('prompt_cache_hit_tokens',0)*self.prices['cached_input']+
                            max(0,usage.get('prompt_tokens',0)-usage.get('prompt_cache_hit_tokens',0))*self.prices['input']+
                            usage.get('completion_tokens',0)*self.prices['output'])/1_000_000
                    except (ValueError,AttributeError,TypeError):actual=None
                    self.budget.settle(reserve,actual)
                if response.status_code in (429,500,502,503,504) and attempt<2:
                    await self._delay(attempt,cancel);continue
                errors={401:'DeepSeek API Key 无效，请在设置中更换',402:'DeepSeek 余额不足，请充值后继续',
                        403:'DeepSeek 访问被拒绝，请检查账户权限',429:'DeepSeek 请求繁忙，请稍后重试',
                        400:'DeepSeek 请求未被接受，请检查模型能力或缩小图片范围'}
                if response.status_code!=200:
                    raise ProviderError(errors.get(response.status_code,'DeepSeek 服务暂时不可用，请稍后重试'),response.status_code)
                try:
                    data=response.json();choice=data['choices'][0]
                    if usage_callback:usage_callback(data.get('usage',{}))
                    if choice.get('finish_reason')=='length':raise ProviderError('模型输出达到上限，当前阶段未完成；已保存的草稿可恢复',code='output_truncated',max_tokens=max_tokens,usage=data.get('usage',{}))
                    return choice['message'],data.get('model',MODEL)
                except (KeyError,IndexError,ValueError,TypeError):
                    raise ProviderError('DeepSeek 返回格式无效，可重试该题') from None
        raise ProviderError('DeepSeek 请求失败')

    async def _delay(self,attempt,cancel):
        for _ in range(10*(attempt+1)):
            if cancel and cancel.is_set():raise AgentCancelled('任务已取消')
            await asyncio.sleep(.1)

    async def json(self,messages,**options):
        message,model=await self.request(messages,**options)
        try:
            value=json.loads(message.get('content') or '')
            if not isinstance(value,dict):raise ValueError()
            return value,model
        except (ValueError,TypeError):raise ProviderError('模型未返回完整 JSON，草稿已保留，可重试',code='invalid_json') from None

    async def test(self):
        value,_=await self.json([{'role':'system','content':'Return json only: {"ok":true}.'},
                                {'role':'user','content':'连接测试，返回 {"ok":true}。'}],max_tokens=64)
        if value.get('ok') is not True:raise ProviderError('接口已响应，但未通过 JSON 能力测试')
        return {'ok':True,'message':'DeepSeek 连接与 JSON 输出测试通过。图片能力将在实际识别时验证。'}
