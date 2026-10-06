from typing import Literal
from pydantic import BaseModel,Field,ConfigDict,model_validator


class Region(BaseModel):
    model_config=ConfigDict(extra='forbid')
    image_id:str
    rect:list[float]=Field(min_length=4,max_length=4)
    role:Literal['question','answer','solution']='question'

    @model_validator(mode='after')
    def valid(self):
        x,y,right,bottom=self.rect
        if not 0<=x<right<=1 or not 0<=y<bottom<=1:raise ValueError('裁剪坐标须为有效的归一化矩形')
        return self


class Figure(Region):
    id:str=Field(pattern=r'^[A-Za-z0-9_-]{1,40}$')
    field:Literal['question_tex','answer_tex','solution_tex']='question_tex'


class Classification(BaseModel):
    collection_code:str
    point_code:str
    reason:str=''


class EditableForm(BaseModel):
    collection_code:str=Field(max_length=80)
    point_code:str=Field(max_length=80)
    type:Literal['single','multi','fill','long']
    question_tex:str=Field(max_length=60000)
    options:list[str]=Field(default_factory=list,max_length=4)
    answer_tex:str=Field(default='',max_length=60000)
    solution_tex:str=Field(default='',max_length=60000)


class SolveResult(BaseModel):
    answer_tex:str=Field(default='',max_length=60000)
    solution_tex:str=Field(default='',max_length=60000)
    answer_conflict:bool=False
    uncertainties:list[str]=Field(default_factory=list,max_length=30)


class Candidate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    type:Literal['single','multi','fill','long']
    question_tex:str=Field(max_length=60000)
    options:list[str]=Field(default_factory=list,max_length=4)
    answer_tex:str=Field(default='',max_length=60000)
    solution_tex:str=Field(default='',max_length=60000)
    collection_code:str='misc'
    point_code:str='6.1'
    classification_reason:str=''
    classification_candidates:list[Classification]=Field(default_factory=list,max_length=3)
    classification_uncertain:bool=False
    uncertainties:list[str]=Field(default_factory=list,max_length=30)
    answer_origin:Literal['original','ai','missing']='missing'
    solution_origin:Literal['original','ai','missing']='missing'
    answer_conflict:bool=False
    original_number:str=''
    regions:list[Region]=Field(min_length=1,max_length=20)
    figures:list[Figure]=Field(default_factory=list,max_length=20)
    expected_figures:int=Field(default=0,ge=0,le=20)


TOOLS=[
    {'type':'function','function':{'name':'read_catalog','description':'读取现有集合和考点，不创建新分类',
                                  'parameters':{'type':'object','properties':{},'required':[]}}},
    {'type':'function','function':{'name':'read_items','description':'读取当前任务中的候选题，包含序号和 ID',
                                  'parameters':{'type':'object','properties':{},'required':[]}}},
    {'type':'function','function':{'name':'update_candidate','description':'修改当前任务一题的文字、分类或不确定说明，不修改正式题库',
        'parameters':{'type':'object','properties':{'item_id':{'type':'string'},'revision':{'type':'integer'},
                       'changes':{'type':'object'}},'required':['item_id','revision','changes']}}},
    {'type':'function','function':{'name':'reprocess_items','description':'按当前原图区域重新识别当前任务中的指定题目',
        'parameters':{'type':'object','properties':{'item_ids':{'type':'array','items':{'type':'string'}}},'required':['item_ids']}}},
    {'type':'function','function':{'name':'restructure_candidates','description':'拆分或合并当前任务的候选草稿；groups 每组是同一题的原图区域，坐标来自 read_items。原草稿保留为已跳过，随后重识别新区域。不能修改正式题目。',
        'parameters':{'type':'object','properties':{
            'items':{'type':'array','items':{'type':'object','properties':{'id':{'type':'string'},'revision':{'type':'integer'}},'required':['id','revision']}},
            'groups':{'type':'array','items':{'type':'array','items':{'type':'object','properties':{'image_id':{'type':'string'},'rect':{'type':'array','items':{'type':'number'}}},'required':['image_id','rect']}}}},'required':['items','groups']}}},
]
