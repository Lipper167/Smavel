import asyncio, json, os, re, time
from pathlib import Path
from urllib.request import Request as UrlRequest, urlopen
from urllib.error import HTTPError, URLError
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

BASE=Path(__file__).resolve().parent
load_dotenv(BASE/'.env')
def env_key(name):return os.environ.get(name,'').strip().strip('"').strip("'")
app=FastAPI(title='Smavel Multi-AI API', docs_url='/docs')
CATEGORIES={'Attractions':15,'Public safety':18,'Conflict risk':12,'Scams':8,'Affordability':10,'Language access':6,'Transport':7,'Healthcare':5,'Climate & disasters':6,'Visa ease':4,'Accessibility':4,'Sustainability':5}
SYSTEM='You are Smavel, an SDG 11 travel research assistant. Output a single valid JSON object, without markdown. Scores are cautious estimates, not verified real-time facts. Avoid visa approval promises.'
class Request(BaseModel):
    country:str=Field(min_length=2,max_length=80)
    nationality:str=Field(default='Indian',max_length=80)
    budget:str=Field(default='mid-range',max_length=40)
    month:str=Field(default='flexible',max_length=40)
    interests:str=Field(default='culture, nature',max_length=150)

@app.get('/')
def home():return FileResponse(BASE/'static'/'index.html')
@app.get('/health')
def health():
    names=[name for name,key in [('groq','GROQ_API_KEY'),('openrouter','OPENROUTER_API_KEY'),('cloudflare','CLOUDFLARE_API_TOKEN')] if env_key(key)]
    return {'status':'ok','api_key_configured':bool(names),'configured_providers':names}
@app.get('/api/models')
def models():
    return {'configured_providers':health()['configured_providers'], 'models':{'groq':os.getenv('GROQ_MODEL','') or 'auto-detected','openrouter':'openrouter/free','cloudflare':os.getenv('CLOUDFLARE_MODEL','') or 'auto-detected'},'note':'Configured models are not guaranteed available or within free quotas.'}

class ProviderError(Exception):
    def __init__(self,msg,code=None):
        super().__init__(msg);self.code=code

def request_json(url,payload,headers,timeout=50,retries=1):
    # Cloudflare (Groq) rejects the default Python-urllib User-Agent with HTTP 403, so send our own.
    headers={'User-Agent':'Smavel/1.0 (+https://smavel.local)','Accept':'application/json',**headers}
    body=json.dumps(payload).encode('utf-8')
    for attempt in range(retries+1):
        req=UrlRequest(url,data=body,headers=headers,method='POST')
        try:
            with urlopen(req,timeout=timeout) as resp:return json.load(resp)
        except HTTPError as e:
            detail=''
            try:detail=e.read().decode('utf-8','ignore')[:300]
            except Exception:pass
            if e.code in (429,500,502,503,504) and attempt<retries:
                time.sleep(2);continue
            raise ProviderError(detail or str(e),e.code)
        except (URLError,TimeoutError,OSError) as e:
            if attempt<retries:time.sleep(1);continue
            raise ProviderError('Network error: '+str(e))

def get_json(url,headers,timeout=20):
    headers={'User-Agent':'Smavel/1.0 (+https://smavel.local)','Accept':'application/json',**headers}
    try:
        with urlopen(UrlRequest(url,headers=headers,method='GET'),timeout=timeout) as resp:return json.load(resp)
    except HTTPError as e:
        raise ProviderError(e.read().decode('utf-8','ignore')[:300] or str(e),e.code)
    except (URLError,TimeoutError,OSError) as e:
        raise ProviderError('Network error: '+str(e))

def rank_models(ids,prefs,banned):
    ids=[i for i in ids if not any(b in i.lower() for b in banned)]
    out=[]
    for p in prefs:
        out+= [i for i in ids if p in i.lower() and i not in out]
    out+=[i for i in ids if i not in out]
    return out

def parse_json(s):
    if not isinstance(s,str) or not s.strip():raise ValueError('Empty response')
    s=re.sub(r'<think>.*?</think>','',s,flags=re.S).strip()
    if s.startswith('```'):
        s=re.sub(r'^```(?:json)?\s*','',s,flags=re.I)
        s=re.sub(r'\s*```$','',s)
    try:return json.loads(s)
    except json.JSONDecodeError:
        start=s.find('{');end=s.rfind('}')
        if start<0 or end<start:raise ValueError('Response was not JSON')
        return json.loads(s[start:end+1])

def chat_text(result):
    msg=result['choices'][0]['message']
    return msg.get('content') or ''

def groq(prompt):
    auth={'Content-Type':'application/json','Authorization':'Bearer '+env_key('GROQ_API_KEY')}
    candidates=[]
    pref=os.getenv('GROQ_MODEL','').strip()
    if pref:candidates.append(pref)
    try:  # ask Groq which models this key can really use (names change over time)
        data=get_json('https://api.groq.com/openai/v1/models',auth)
        ids=[m['id'] for m in data.get('data',[]) if m.get('active',True)]
        candidates+=rank_models(ids,['gpt-oss-120b','llama-3.3-70b','llama-4','qwen','kimi','gpt-oss-20b','llama'],
                                ['whisper','guard','tts','orpheus','playai','compound','safeguard','embed'])[:6]
    except ProviderError as e:
        if e.code in (401,403):raise
        candidates+=['llama-3.3-70b-versatile','llama-3.1-8b-instant']
    last=ProviderError('No Groq models available',404)
    for model in dict.fromkeys(candidates):
        for use_json_mode in (True,False):
            body={'model':model,'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':prompt}],
                  'temperature':0.3,'max_tokens':3500}
            if use_json_mode:body['response_format']={'type':'json_object'}
            try:
                result=request_json('https://api.groq.com/openai/v1/chat/completions',body,auth)
                return model,parse_json(chat_text(result))
            except ProviderError as e:
                last=e
                if e.code==400 and use_json_mode:continue   # model lacks JSON mode -> retry without
                if e.code in (400,404):break                 # bad/retired model -> next model
                raise
            except ValueError as e:
                last=ProviderError('Bad JSON from '+model);break
    raise last

def openrouter(prompt):
    auth={'Content-Type':'application/json','Authorization':'Bearer '+env_key('OPENROUTER_API_KEY'),
          'HTTP-Referer':os.environ.get('SITE_URL','http://127.0.0.1:8000'),'X-Title':'Smavel'}
    candidates=['openrouter/free']
    try:  # free models come and go, so ask OpenRouter which ones exist right now
        data=get_json('https://openrouter.ai/api/v1/models',{})
        ids=[m['id'] for m in data.get('data',[]) if isinstance(m,dict) and str(m.get('id','')).endswith(':free')]
        candidates+=rank_models(ids,['llama-3.3-70b','gpt-oss-120b','qwen','deepseek','gemma','mistral','llama'],
                                ['image','vision','audio','embed','guard','safeguard','lyria','nano'])[:5]
    except ProviderError:
        candidates+=['meta-llama/llama-3.3-70b-instruct:free','openai/gpt-oss-120b:free']
    first=last=None
    for model in dict.fromkeys(candidates):
        try:
            result=request_json('https://openrouter.ai/api/v1/chat/completions',{
                'model':model,
                'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':prompt}],
                'temperature':0.3,'max_tokens':3500
            },auth)
            if 'error' in result and 'choices' not in result:
                err=result['error']
                raise ProviderError(str(err)[:300],err.get('code') if isinstance(err,dict) else None)
            return model,parse_json(chat_text(result))
        except (ProviderError,ValueError,KeyError,IndexError,TypeError) as e:
            last=e
            if isinstance(e,ProviderError):
                flagged=e.code==403 and any(w in str(e).lower() for w in ('moderation','flagged'))   # this model's content filter, not a bad key
                if e.code in (401,402) or (e.code==403 and not flagged):raise
            if first is None and not (isinstance(e,ProviderError) and e.code==404):first=e   # keep the real cause, not a later "model not found"
    raise first or last

def cloudflare(prompt):
    acct=env_key('CLOUDFLARE_ACCOUNT_ID')
    if not acct:raise ProviderError('Set CLOUDFLARE_ACCOUNT_ID')
    base=f'https://api.cloudflare.com/client/v4/accounts/{acct}/ai'
    auth={'Content-Type':'application/json','Authorization':'Bearer '+env_key('CLOUDFLARE_API_TOKEN')}
    candidates=[]
    pref=os.getenv('CLOUDFLARE_MODEL','').strip()
    if pref:candidates.append(pref)
    try:  # ask Cloudflare which text models exist right now (names change over time)
        data=get_json(base+'/models/search?task=Text%20Generation&per_page=100',auth)
        ids=[m['name'] for m in data.get('result',[]) if isinstance(m,dict) and str(m.get('name','')).startswith('@cf/')]
        candidates+=rank_models(ids,['llama-3.3-70b-instruct-fp8-fast','gpt-oss-120b','llama-4-scout','llama-3.1-8b-instruct','qwen','gemma','mistral'],
                                ['guard','embed','coder','math','whisper','tts','vision','awq','int8','sea-lion','tinyllama','phi-2','zephyr','llama-2','7b'])[:6]
    except ProviderError as e:
        if e.code in (401,403):raise
        candidates+=['@cf/meta/llama-3.3-70b-instruct-fp8-fast','@cf/openai/gpt-oss-120b','@cf/meta/llama-3.1-8b-instruct']
    last=ProviderError('No Cloudflare models available',404)
    variants=[{'response_format':{'type':'json_object'}},{}]   # retry without JSON mode if the model rejects it
    for model in dict.fromkeys(candidates):
        for extra in variants:
            body={'model':model,'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':prompt}],'temperature':0.3,'max_tokens':3500,**extra}
            try:
                result=request_json(base+'/v1/chat/completions',body,auth)
                return model,parse_json(chat_text(result))
            except ProviderError as e:
                last=e
                if e.code in (400,422) and extra:continue   # unsupported option -> simpler request
                if e.code in (400,404,422):break             # bad/retired model -> next model
                raise                                        # 401/403/429 (daily allowance used up) -> stop
            except (ValueError,KeyError,IndexError,AttributeError):
                last=ProviderError('Bad response from '+model);break
    raise last

PROVIDERS=[('groq','GROQ_API_KEY',groq),('openrouter','OPENROUTER_API_KEY',openrouter),('cloudflare','CLOUDFLARE_API_TOKEN',cloudflare)]

def to_score(v):
    if isinstance(v,(int,float)):n=float(v)
    elif isinstance(v,str):
        m=re.search(r'-?\d+(?:\.\d+)?',v)
        if not m:raise ValueError('Bad score')
        n=float(m.group())
    else:raise ValueError('Bad score')
    return max(0,min(10,int(round(n))))

def norm(k):return re.sub(r'[^a-z]','',str(k).lower())

def score_categories(data):
    raw=data.get('category_scores') if isinstance(data,dict) else None
    if not isinstance(raw,dict):raise ValueError('Missing category scores')
    lookup={norm(k):v for k,v in raw.items()}  # tolerate case/punctuation differences in keys
    scores={}
    for k in CATEGORIES:
        nk=norm(k)
        if nk not in lookup:
            alt=[v for kk,v in lookup.items() if kk.startswith(nk[:8])]
            if not alt:raise ValueError('Incomplete category scores')
            lookup[nk]=alt[0]
        scores[k]=to_score(lookup[nk])
    total=round(sum(scores[k]*w/10 for k,w in CATEGORIES.items()))
    return scores,total

def safe_text(value,default='Not available'):
    return str(value).strip()[:1400] if isinstance(value,str) and value.strip() else default

def list_text(value,limit=9):
    return [safe_text(v) for v in value[:limit] if isinstance(v,str)] if isinstance(value,list) else []

def prompt_for(req):
    return f'''Assess tourism suitability for destination {req.country}; traveller nationality {req.nationality}, budget {req.budget}, travel month {req.month}, interests {req.interests}.
Return ONLY one JSON object with these exact keys:
country (string), summary (string), recommendation (string), warning (string), cities (array of 3 objects with name and reason), highlights (array of strings), precautions (array of strings), travel_tips (array of 5-7 practical destination-specific tips), daily_budget_usd (string), visa_note (string), sources_to_check (array of official site names), category_scores (object with EXACTLY these keys and integer values 0-10): {list(CATEGORIES)}.
10 is best travel suitability; for Conflict risk, 10 means low risk. Mark uncertainty. Do not invent real-time conflict conditions, prices, safety advisories or visa eligibility. Include sustainability considerations. Keep text concise.'''

async def one_provider(name,fn,prompt):
    try:
        model,data=await asyncio.wait_for(asyncio.to_thread(fn,prompt),timeout=100)
        scores,total=score_categories(data)
        print('Smavel provider completed:',name,total)
        return {'provider':name,'status':'ok','score':total,'category_scores':scores,'model':model,'data':data}
    except Exception as exc:
        code=getattr(exc,'code',None)
        hint={401:'Invalid API key',403:'Access denied (check key/region)',402:'Credits/quota needed',404:'Model not found',429:'Rate limit / quota reached'}.get(code)
        print('Smavel provider unavailable:',name,type(exc).__name__,code or '',str(exc)[:200].replace('\n',' ') if not isinstance(exc,ProviderError) or code not in (401,403) else '')
        reason=hint or ('HTTP '+str(code) if code else ('Timed out' if isinstance(exc,(asyncio.TimeoutError,TimeoutError)) else type(exc).__name__+': '+str(exc)[:80]))
        return {'provider':name,'status':'unavailable','reason':reason}

@app.post('/api/analyze')
async def analyze(req:Request):
    if not re.fullmatch(r"[\w\s.,()'-]+",req.country,re.UNICODE):raise HTTPException(422,'Enter a valid country name')
    active=[(name,fn) for name,key,fn in PROVIDERS if env_key(key)]
    if not active:raise HTTPException(503,'Configure at least one AI API key in .env')
    prompt=prompt_for(req)
    results=await asyncio.gather(*(one_provider(name,fn,prompt) for name,fn in active))
    good=[r for r in results if r['status']=='ok']
    if not good:
        why='; '.join(f"{r['provider']}: {r.get('reason','failed')}" for r in results)
        raise HTTPException(502,'All AI providers failed -> '+why)
    # Equal-weight consensus per criterion; then original weighted scoring.
    scores={k:round(sum(r['category_scores'][k] for r in good)/len(good),1) for k in CATEGORIES}
    total=round(sum(scores[k]*w/10 for k,w in CATEGORIES.items()))
    primary=good[0]['data']
    # Combine useful independent findings without fabricating a synthesis.
    def combine_list(key,max_items):
        items=[];seen=set()
        for r in good:
            for v in list_text(r['data'].get(key),max_items):
                if v.lower() not in seen:items.append(v);seen.add(v.lower())
        return items[:max_items]
    cities=[];seen=set()
    for r in good:
        for city in r['data'].get('cities',[]) if isinstance(r['data'].get('cities'),list) else []:
            if isinstance(city,dict) and isinstance(city.get('name'),str) and city['name'].lower() not in seen:
                cities.append({'name':safe_text(city['name']),'reason':safe_text(city.get('reason'))});seen.add(city['name'].lower())
    return {'country':safe_text(primary.get('country'),req.country),'summary':safe_text(primary.get('summary')),
        'recommendation':safe_text(primary.get('recommendation')),'warning':safe_text(primary.get('warning')),
        'cities':cities[:3],'highlights':combine_list('highlights',8),'precautions':combine_list('precautions',8),
        'travel_tips':combine_list('travel_tips',8),'daily_budget_usd':safe_text(primary.get('daily_budget_usd')),
        'visa_note':safe_text(primary.get('visa_note')),'sources_to_check':combine_list('sources_to_check',8),
        'category_scores':scores,'score':total,'weights':CATEGORIES,'successful_providers':len(good),
        'providers':[{k:v for k,v in r.items() if k in ('provider','status','score','reason','model','category_scores')} for r in results],
        'disclaimer':'AI-generated, unverified estimates. The score averages available model opinions; it is not a factual safety certification. Verify official travel advisories, visa rules, weather and prices before booking.'}
