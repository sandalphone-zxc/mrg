"""Parse one JSON object without executing text or repairing business values."""
import json
import re

class OutputFormatError(ValueError):
    def __init__(self,code,content='',finish_reason=None):
        self.code,self.content,self.finish_reason=code,content,finish_reason
        super().__init__(code)
    def metadata(self):return {'code':self.code,'finish_reason':self.finish_reason,'content_characters':len(self.content)}


def parse_object_response(result):
    try:
        choice=result['choices'][0];message=choice['message'];content=message.get('content');finish=choice.get('finish_reason')
    except (KeyError,IndexError,TypeError,AttributeError):raise OutputFormatError('invalid_envelope') from None
    if isinstance(content,list):
        if any(not isinstance(x,dict) or x.get('type')!='text' or not isinstance(x.get('text'),str) for x in content):raise OutputFormatError('unsupported_content',finish_reason=finish)
        content=''.join(x['text'] for x in content)
    if finish in ('length','max_tokens'):raise OutputFormatError('truncated',finish_reason=finish)
    if finish in ('content_filter','tool_calls','function_call'):raise OutputFormatError('non_final_content',finish_reason=finish)
    if not isinstance(content,str) or not content.strip():raise OutputFormatError('empty_content',finish_reason=finish)
    text=content.lstrip('\ufeff').strip()
    if text.startswith('```'):
        match=re.fullmatch(r'```(?:json)?\s*\n?([\s\S]*?)\s*```',text,re.IGNORECASE)
        if match:text=match.group(1).strip()
    try:
        value=json.loads(text)
    except json.JSONDecodeError:
        # Permit explanatory prose around exactly one complete object. Never skip
        # an invalid opening delimiter to accept a nested fragment instead.
        matches=list(re.finditer(r'[\[{]',text))
        if not matches:raise OutputFormatError('invalid_json',content,finish) from None
        start=matches[0].start()
        if text[start]!='{':raise OutputFormatError('not_object',finish_reason=finish)
        try:value,end=json.JSONDecoder().raw_decode(text,start)
        except json.JSONDecodeError:raise OutputFormatError('invalid_json',content,finish) from None
        if re.search(r'[\[\]{}]',text[end:]):raise OutputFormatError('ambiguous_objects',content,finish)
    if not isinstance(value,dict):raise OutputFormatError('not_object',finish_reason=finish)
    return value


def object_candidates(content):
    """Return decodable object candidates for a caller with a real contract.

    This never changes the default strict parser. Contract-aware callers may use
    it after an ambiguous response and accept a candidate only when exactly one
    satisfies their expected shape or validation rules.
    """
    if not isinstance(content,str):return []
    decoder=json.JSONDecoder();values=[];seen=set()
    for match in re.finditer(r'{',content):
        try:value,_=decoder.raw_decode(content,match.start())
        except json.JSONDecodeError:continue
        if not isinstance(value,dict):continue
        key=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
        if key not in seen:seen.add(key);values.append(value)
    return values
