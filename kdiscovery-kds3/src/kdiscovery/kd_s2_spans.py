"""Conservative lexical boundaries; never treat a TS parameter type as a body."""
import re


def matching(text,start,opening,closing):
    depth=0
    for i in range(start,len(text)):
        if text[i]==opening:depth+=1
        elif text[i]==closing:
            depth-=1
            if depth==0:return i
    return None


def body_start(text, match):
    header=text[match.start():match.end()]
    if re.search(r'\bclass\b',header):return text.find('{',match.end())
    if header.rstrip().endswith('=>'):return text.find('{',match.end())
    parameter=text.find('(',match.start(),match.end()+1)
    if parameter<0:return -1
    end=matching(text,parameter,'(',')')
    if end is None:return -1
    i=end+1
    while i<len(text) and text[i].isspace():i+=1
    typed=i<len(text) and text[i]==':'
    if typed:i+=1
    type_start=i
    angle=0
    while i<len(text):
        ch=text[i]
        if ch==';':return -1
        if ch=='<':angle+=1
        elif ch=='>' and angle:angle-=1
        elif ch in '([':
            end=matching(text,i,ch,')' if ch=='(' else ']')
            if end is None:return -1
            i=end
        elif ch=='{':
            end=matching(text,i,'{','}')
            if end is None:return -1
            # A leading object return type, generic type member, or a type
            # followed by the actual implementation is not executable code.
            suffix=text[end+1:].lstrip()
            prefix=text[type_start:i].strip()
            is_type=typed and (angle>0 or not prefix or suffix.startswith(('{','|','&','[',']','>')))
            if is_type:i=end
            else:return i
        i+=1
    return -1
