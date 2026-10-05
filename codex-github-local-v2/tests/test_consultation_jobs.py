import json
import os
from pathlib import Path
import tempfile
import sys
import time
import unittest
from unittest.mock import Mock
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))

from codex_github_local_v2.collaboration_api import mcp_dispatch
from codex_github_local_v2.consultation_jobs import ConsultationJobs


class ConsultationJobTests(unittest.TestCase):
    def test_completed_background_result_is_readable_after_reopening_store(self):
        with tempfile.TemporaryDirectory() as root:
            jobs=ConsultationJobs(Path(root)/'jobs')
            reply='完整结果'*100000
            bridge=Mock(async_consultations=True,jobs=jobs,consult=lambda *_:{'model':'fixture','text':reply})
            first=mcp_dispatch({'method':'tools/call','params':{'name':'consult_model','arguments':{'index':0,'prompt':'frozen question'}}},bridge)
            job_id=json.loads(first['content'][0]['text'])['job_id']
            end=time.monotonic()+5
            while jobs[job_id]['status']=='running':
                self.assertLess(time.monotonic(),end)
                time.sleep(.01)
            restored=ConsultationJobs(Path(root)/'jobs')
            bridge.jobs=restored
            result=mcp_dispatch({'method':'tools/call','params':{'name':'get_consultation','arguments':{'job_id':job_id}}},bridge)
            result=json.loads(result['content'][0]['text'])
            self.assertEqual(result['status'],'completed')
            self.assertEqual(result['text'],reply)
            self.assertNotIn('request',result)
            payload=json.loads(restored.path(job_id).read_text())
            self.assertEqual(payload['request']['prompt'],'frozen question')
            if os.name=='posix':self.assertEqual(restored.path(job_id).stat().st_mode&0o777,0o600)

    def test_dead_worker_is_reported_unknown_without_replaying_paid_request(self):
        with tempfile.TemporaryDirectory() as root:
            jobs=ConsultationJobs(root);job_id=str(uuid.uuid4())
            jobs.start(job_id,{'job_id':job_id,'status':'running'},{'index':0,'prompt':'saved'})
            payload=json.loads(jobs.path(job_id).read_text());payload['worker']=None
            jobs.path(job_id).write_text(json.dumps(payload))
            bridge=Mock(async_consultations=True,jobs=ConsultationJobs(root))
            result=mcp_dispatch({'method':'tools/call','params':{'name':'get_consultation','arguments':{'job_id':job_id}}},bridge)
            result=json.loads(result['content'][0]['text'])
            self.assertEqual(result['status'],'interrupted')
            self.assertEqual(result['error'],'consultation_outcome_unknown')
            bridge.consult.assert_not_called()
            self.assertEqual(json.loads(jobs.path(job_id).read_text())['result']['status'],'running')

    def test_invalid_ids_and_broken_records_do_not_read_outside_job_directory(self):
        with tempfile.TemporaryDirectory() as root:
            jobs=ConsultationJobs(Path(root)/'jobs')
            (Path(root)/'secret.json').write_text('private')
            self.assertEqual(jobs.get('../secret',{'error':'not_found'}),{'error':'not_found'})
            job_id=str(uuid.uuid4());jobs.path(job_id).write_text('{broken')
            self.assertEqual(jobs[job_id]['error'],'consultation_record_unreadable')


if __name__=='__main__':unittest.main()
