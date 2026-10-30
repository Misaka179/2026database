"""Private work-description attachments and collection audience lookup."""
import base64
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import ZipFile
from xml.etree import ElementTree
from .db import one, all_rows
from .collection_management import CollectionManagement

MAX_FILE = 2 * 1024 * 1024
MIMES = {'.pdf':'application/pdf','.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
         '.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','.txt':'text/plain',
         '.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png'}


def decode_attachments(attachments):
    from .service import require, DomainError
    require(isinstance(attachments,list) and len(attachments)<=3,'工作说明附件最多3个',422)
    result=[]
    for item in attachments:
        filename=item['filename'].strip()
        suffix=PurePosixPath(filename).suffix.lower()
        require(0<len(filename)<=200 and '/' not in filename and '\\' not in filename
                and not any(ord(ch)<32 for ch in filename) and suffix in MIMES,'附件名称或格式无效',422)
        try:
            data=base64.b64decode(item['file_base64'],validate=True)
            require(0<len(data)<=MAX_FILE,'每个附件须为非空文件且不超过2MB',422)
            if suffix=='.pdf':
                require(data.startswith(b'%PDF-') and b'%%EOF' in data[-1024:],'PDF文件内容无效',422)
            elif suffix in ('.docx','.xlsx'):
                with ZipFile(BytesIO(data)) as archive:
                    entries=archive.infolist()
                    require(len(entries)<=2000 and sum(e.file_size for e in entries)<=20*1024*1024,
                            '文档解压后内容过大',422)
                    names=archive.namelist()
                    main='word/document.xml' if suffix=='.docx' else 'xl/workbook.xml'
                    require('[Content_Types].xml' in names and main in names
                            and not any('vbaproject' in n.lower() for n in names),'Office文档格式不匹配',422)
                    require(archive.testzip() is None,'Office文档已损坏',422)
                    for path,root in [('[Content_Types].xml','Types'),(main,'document' if suffix=='.docx' else 'workbook')]:
                        xml=archive.read(path)
                        require(b'<!DOCTYPE' not in xml.upper() and b'<!ENTITY' not in xml.upper(),'文档XML内容无效',422)
                        require(ElementTree.fromstring(xml).tag.split('}')[-1]==root,'Office文档结构无效',422)
            elif suffix=='.txt':
                require(b'\x00' not in data,'文本文件内容无效',422)
                try:data.decode('utf-8-sig')
                except UnicodeDecodeError:data.decode('gb18030')
            else:
                from PIL import Image
                with Image.open(BytesIO(data)) as img:
                    expected='PNG' if suffix=='.png' else 'JPEG'
                    require(img.format==expected and img.width*img.height<=20000000,'图片内容或尺寸无效',422)
                    img.verify()
        except DomainError:raise
        except Exception as exc:raise DomainError('附件内容无效或无法读取：'+filename,422) from exc
        result.append({'filename':filename,'mime_type':MIMES[suffix],'content':data,'size_bytes':len(data)})
    return result


class CollectionSupport(CollectionManagement):
    def collection_participants(self,actor,business_id=None,student_id='',group_id=None):
        from .service import require
        with self.db.transaction() as c:
            a=self.actor(c,actor,('SUPER','NORMAL'));ids=None
            if group_id is not None:
                g=one(c,'SELECT * FROM business_group WHERE group_id=%s',(group_id,));require(g,'小组不存在',404)
                require(business_id is None or business_id==g['business_id'],'小组不属于该业务',422)
                self._active_business(c,g['business_id']);self._collection_scope(c,a,g['business_id'],group_id)
                people=self._group_people(c,group_id)
                return [p for p in all_rows(c,'SELECT student_id,name FROM student ORDER BY student_id') if p['student_id'] in people and student_id.strip() in p['student_id']]
            if business_id is not None:
                self._active_business(c,business_id)
                self._collection_scope(c,a,business_id);ids=[business_id]
            elif a['_role']=='NORMAL':
                ids=[r['business_id'] for r in all_rows(c,"SELECT m.business_id FROM collection_manager m JOIN business b ON b.business_id=m.business_id WHERE m.admin_id=%s AND b.status='ACTIVE'",(a['_id'],))]
                groups=[r['group_id'] for r in all_rows(c,"SELECT m.group_id FROM collection_group_manager m JOIN business_group g ON g.group_id=m.group_id JOIN business b ON b.business_id=g.business_id WHERE m.admin_id=%s AND b.status='ACTIVE'",(a['_id'],))]
                group_people=set().union(*(self._group_people(c,g) for g in groups)) if groups else set()
                if not ids:return [p for p in all_rows(c,'SELECT student_id,name FROM student ORDER BY student_id') if p['student_id'] in group_people and student_id.strip() in p['student_id']]
            sql="SELECT s.student_id,s.name FROM student s WHERE s.status='ACTIVE'";args=[]
            if ids is not None:
                placeholders=','.join(['%s']*len(ids))
                sql+=f""" AND (EXISTS(SELECT 1 FROM slot_member m JOIN service_slot t ON t.slot_id=m.slot_id
                    WHERE m.student_id=s.student_id AND t.business_id IN ({placeholders}) AND t.status='ACTIVE')
                    OR EXISTS(SELECT 1 FROM business_member m WHERE m.student_id=s.student_id AND m.business_id IN ({placeholders})
                    AND m.effective_from<=%s AND (m.effective_until IS NULL OR m.effective_until>%s)))"""
                args.extend(ids+ids+[self.clock().date(),self.clock().date()])
            if student_id:sql+=' AND LOCATE(%s,s.student_id)>0';args.append(student_id.strip())
            rows=list(all_rows(c,sql+' ORDER BY s.student_id',args))
            if a['_role']=='NORMAL' and business_id is None:
                by_id={p['student_id']:p for p in rows}
                for p in all_rows(c,'SELECT student_id,name FROM student ORDER BY student_id'):
                    if p['student_id'] in group_people and student_id.strip() in p['student_id']:by_id[p['student_id']]=p
                rows=sorted(by_id.values(),key=lambda p:p['student_id'])
            return rows

    def collection_attachment(self,actor,collection_id,attachment_id):
        from .service import require
        with self.db.transaction() as c:
            a=self.actor(c,actor,('SUPER','NORMAL','STUDENT'))
            collection=one(c,'SELECT * FROM hour_collection WHERE collection_id=%s',(collection_id,))
            require(collection,'征集不存在',404)
            if a['_role']=='NORMAL':self._collection_scope(c,a,collection['business_id'],collection.get('group_id'))
            if a['_role']=='STUDENT':
                require(one(c,'SELECT 1 FROM collection_person WHERE collection_id=%s AND student_id=%s',
                            (collection_id,a['_id'])),'不在本次征集范围',403)
            row=one(c,'SELECT * FROM collection_attachment WHERE collection_id=%s AND attachment_id=%s',
                    (collection_id,attachment_id))
            require(row,'附件不存在',404)
            return row
