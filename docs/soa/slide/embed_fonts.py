"""Embed complete static TTF faces as uncompressed EOT per W3C EOT v2.1.
No outline modification, subsetting, font installation or external upload.
"""
from pathlib import Path
import struct, zipfile, xml.etree.ElementTree as ET, json, hashlib

ROOT=Path(__file__).resolve().parent
P='http://schemas.openxmlformats.org/presentationml/2006/main'
A='http://schemas.openxmlformats.org/drawingml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
REL='http://schemas.openxmlformats.org/package/2006/relationships'
CT='http://schemas.openxmlformats.org/package/2006/content-types'
for pre,uri in [('p',P),('a',A),('r',R)]: ET.register_namespace(pre,uri)

def parse_font(file):
    data=file.read_bytes()
    assert data[:4]==b'\x00\x01\x00\x00','Static TrueType required'
    tables={}
    for i in range(struct.unpack_from('>H',data,4)[0]):
        tag,checksum,off,size=struct.unpack_from('>4sIII',data,12+i*16)
        tables[tag.decode()]=data[off:off+size]
    assert 'fvar' not in tables
    names={}; n=tables['name']; count,stroff=struct.unpack_from('>HH',n,2)
    for i in range(count):
        plat,enc,lang,nid,size,off=struct.unpack_from('>6H',n,6+i*12)
        if plat==3 and lang==1033: names[nid]=n[stroff+off:stroff+off+size].decode('utf-16-be')
    os=tables['OS/2']; flags=struct.unpack_from('>H',os,8)[0]
    assert not flags & (2|4|512),f'Unsupported embedding rights {flags}'
    glyphs=set(); cmap=tables['cmap']
    for i in range(struct.unpack_from('>H',cmap,2)[0]):
        platform,enc,off=struct.unpack_from('>HHI',cmap,4+i*8)
        fmt=struct.unpack_from('>H',cmap,off)[0]
        if fmt==4:
            seg=struct.unpack_from('>H',cmap,off+6)[0]//2
            ends=struct.unpack_from('>'+str(seg)+'H',cmap,off+14)
            starts=struct.unpack_from('>'+str(seg)+'H',cmap,off+16+seg*2)
            for start,end in zip(starts,ends): glyphs.update(range(start,end+1))
        elif fmt==12:
            for j in range(struct.unpack_from('>I',cmap,off+12)[0]):
                start,end,gid=struct.unpack_from('>III',cmap,off+16+j*12);glyphs.update(range(start,end+1))
    header=bytearray(82)
    struct.pack_into('<IIII',header,0,0,len(data),0x00020001,0)
    header[16:26]=os[32:42]
    header[26]=1;header[27]=int(bool(struct.unpack_from('>H',os,62)[0]&1))
    struct.pack_into('<IHH',header,28,struct.unpack_from('>H',os,4)[0],flags,0x504c)
    struct.pack_into('<4I',header,36,*struct.unpack_from('>4I',os,42))
    struct.pack_into('<2I',header,52,*struct.unpack_from('>2I',os,78))
    struct.pack_into('<I',header,60,struct.unpack_from('>I',tables['head'],8)[0])
    payload=bytes(header)
    for nid in [1,2,5,4]:
        name=names[nid].encode('utf-16-le');payload+=struct.pack('<H',len(name))+name+b'\0\0'
    # Last string's NUL is Padding5; then RootStringSize=0.
    payload+=b'\0\0'+data
    payload=struct.pack('<I',len(payload))+payload[4:]
    assert struct.unpack_from('<I',payload)[0]==len(payload)
    assert payload[-len(data):]==data
    return payload,names,flags,glyphs

FACES=[('Geist','regular','Geist-Regular.ttf'),('Geist','bold','Geist-Bold.ttf'),('Geist SemiBold','regular','Geist-SemiBold.ttf'),('Geist Mono','regular','GeistMono-Regular.ttf')]

def embed(deck):
    with zipfile.ZipFile(deck) as z: parts={n:z.read(n) for n in z.namelist()}
    presentation=ET.fromstring(parts['ppt/presentation.xml'])
    presentation.set('embedTrueTypeFonts','1');presentation.set('saveSubsetFonts','0')
    old=presentation.find(f'{{{P}}}embeddedFontLst')
    if old is not None: presentation.remove(old)
    listing=ET.Element(f'{{{P}}}embeddedFontLst')
    # embeddedFontLst belongs after notesSz and before custShowLst/photoAlbum/custDataLst.
    children=list(presentation);after=['sldMasterIdLst','notesMasterIdLst','handoutMasterIdLst','sldIdLst','sldSz','notesSz','smartTags']
    index=max((i+1 for i,c in enumerate(children) if c.tag.split('}')[-1] in after),default=0)
    presentation.insert(index,listing)
    rels=ET.fromstring(parts['ppt/_rels/presentation.xml.rels']); content=ET.fromstring(parts['[Content_Types].xml'])
    if not any(c.get('Extension')=='fntdata' for c in content): ET.SubElement(content,f'{{{CT}}}Default',Extension='fntdata',ContentType='application/x-fontdata')
    groups={}; report=[]
    for i,(family,style,name) in enumerate(FACES,1):
        blob,names,flags,glyphs=parse_font(ROOT/'assets/fonts'/name)
        assert names[1]==family
        relid=f'rIdGeistFull{i}';target=f'fonts/geist-full-{i}.fntdata'
        parts['ppt/'+target]=blob
        ET.SubElement(rels,f'{{{REL}}}Relationship',Id=relid,Type=R+'/font',Target=target)
        if family not in groups:
            groups[family]=ET.SubElement(listing,f'{{{P}}}embeddedFont')
            ET.SubElement(groups[family],f'{{{P}}}font',typeface=family)
        ET.SubElement(groups[family],f'{{{P}}}{style}',{f'{{{R}}}id':relid})
        vi='Tiếng Việt Nguyễn Trường Giang điện năng ước tính tiết kiệm hộ gia đình'
        missing=sorted({c for c in vi if ord(c) not in glyphs})
        assert not missing,missing
        report.append({'family':family,'style':style,'full_font_bytes':len(blob),'fsType':flags,'vietnamese_sample_missing':missing,'sha256_ttf':hashlib.sha256(blob[-struct.unpack_from('<I',blob,4)[0]:]).hexdigest()})
    for name,obj in [('ppt/presentation.xml',presentation),('ppt/_rels/presentation.xml.rels',rels),('[Content_Types].xml',content)]:parts[name]=ET.tostring(obj,encoding='utf-8',xml_declaration=True)
    tmp=deck.with_suffix('.font-embedded.tmp')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
        for name,blob in parts.items():z.writestr(name,blob)
    with zipfile.ZipFile(tmp) as z:assert z.testzip() is None
    tmp.replace(deck)
    return {'deck':str(deck),'fonts':report}

if __name__=='__main__':
    import sys
    print(json.dumps([embed(Path(f)) for f in sys.argv[1:]],ensure_ascii=False)[:200])
