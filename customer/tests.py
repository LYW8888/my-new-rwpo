import json
import uuid
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from . import views
from .models import CustomerProfile, CustomerEvent, SmsChallenge, ServiceRecord

PHONE='13800008000'
CODE='604921'
VALID={'surname':'林','mode':'due_date','dueDate':'2099-01-01','dueTime':'12:00','place':'杭州','gender':'unknown','length':'2','candidateCount':'3'}


class CustomerTest(TestCase):
    def post(self,path,data,client=None):
        return (client or self.client).post('/api/customer/'+path,data=json.dumps(data),content_type='application/json')

    def send(self,phone=PHONE):
        with patch('customer.sms.available',return_value=True), patch('customer.sms.send') as sender, patch('customer.views.secrets.randbelow',return_value=int(CODE)):
            result=self.post('request-code',{'phone':phone})
            self.assertEqual(result.status_code,200)
            sender.assert_called_once_with('+86'+phone,CODE)
            return result.json()['challenge_id']

    def sign_in(self,phone=PHONE):
        challenge=self.send(phone)
        response=self.post('verify-code',{'challenge_id':challenge,'code':CODE})
        self.assertEqual(response.status_code,200)
        return response.json()['customer']

    def save(self,key=None,**changes):
        return self.post('records/save',{'request_key':key or str(uuid.uuid4()),'consent':True,'input':{**VALID,**changes}})

    def test_default_sms_is_disabled_and_does_not_create_a_challenge(self):
        response=self.post('request-code',{'phone':PHONE})
        self.assertEqual(response.status_code,503)
        self.assertEqual(SmsChallenge.objects.count(),0)
        self.assertFalse(self.client.get('/api/customer/session').json()['sms_available'])

    def test_verified_phone_creates_one_passwordless_customer_and_rejects_replay(self):
        challenge=self.send()
        response=self.post('verify-code',{'challenge_id':challenge,'code':CODE})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['customer']['phone_mask'],'138****8000')
        self.assertFalse(get_user_model().objects.get().has_usable_password())
        self.assertNotIn(PHONE,get_user_model().objects.get().username)
        self.assertNotEqual(SmsChallenge.objects.get().code_hash,CODE)
        self.assertNotIn('code',self.client.get('/api/customer/session').json())
        self.post('logout',{})
        self.assertEqual(self.post('verify-code',{'challenge_id':challenge,'code':CODE}).status_code,400)
        self.assertIsNone(self.client.get('/api/customer/session').json()['customer'])
        SmsChallenge.objects.update(created_at=timezone.now()-timedelta(minutes=2))
        same=self.sign_in()
        self.assertEqual(CustomerProfile.objects.count(),1)
        self.assertEqual(same['id'],response.json()['customer']['id'])

    def test_failure_counter_persists_and_locks_challenge(self):
        challenge=self.send()
        for _ in range(5):
            self.assertEqual(self.post('verify-code',{'challenge_id':challenge,'code':'111111'}).status_code,400)
        self.assertEqual(SmsChallenge.objects.get().failures,5)
        self.assertEqual(self.post('verify-code',{'challenge_id':challenge,'code':CODE}).status_code,400)
        self.assertEqual(CustomerProfile.objects.count(),0)

    def test_expired_code_is_rejected(self):
        challenge=self.send(); SmsChallenge.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.post('verify-code',{'challenge_id':challenge,'code':CODE}).status_code,400)

    def test_resend_cooldown_and_daily_cap_stop_provider_calls(self):
        self.send()
        with patch('customer.sms.available',return_value=True),patch('customer.sms.send') as sender:
            self.assertEqual(self.post('request-code',{'phone':PHONE}).status_code,429)
            with override_settings(SMS_DAILY_LIMIT=1):
                self.assertEqual(self.post('request-code',{'phone':'13900008000'}).status_code,429)
            sender.assert_not_called()

    def test_phone_and_ip_budgets_cannot_be_bypassed_by_a_forwarded_header(self):
        self.send()
        SmsChallenge.objects.update(created_at=timezone.now()-timedelta(minutes=2))
        with patch('customer.sms.available',return_value=True),patch('customer.sms.send') as sender:
            with override_settings(SMS_PHONE_HOURLY_LIMIT=1):
                self.assertEqual(self.post('request-code',{'phone':PHONE}).status_code,429)
            with override_settings(SMS_IP_HOURLY_LIMIT=1):
                response=self.client.post('/api/customer/request-code',data=json.dumps({'phone':'13900008000'}),content_type='application/json',HTTP_X_REAL_IP='203.0.113.2')
                self.assertEqual(response.status_code,429)
            sender.assert_not_called()

    def test_successful_resend_invalidates_previous_challenge(self):
        old=self.send(); SmsChallenge.objects.update(created_at=timezone.now()-timedelta(minutes=2))
        new=self.send()
        self.assertEqual(self.post('verify-code',{'challenge_id':old,'code':CODE}).status_code,400)
        self.assertEqual(self.post('verify-code',{'challenge_id':new,'code':CODE}).status_code,200)

    def test_late_provider_response_cannot_reactivate_an_older_challenge(self):
        def newer_request(phone,code):
            old=SmsChallenge.objects.get()
            SmsChallenge.objects.create(phone_hash=old.phone_hash,phone_mask=old.phone_mask,ip_hash=old.ip_hash,
                code_hash='newer-challenge-hash',status='sent',expires_at=timezone.now()+timedelta(minutes=5))
        with patch('customer.sms.available',return_value=True),patch('customer.sms.send',side_effect=newer_request):
            self.assertEqual(self.post('request-code',{'phone':PHONE}).status_code,409)
        old=SmsChallenge.objects.order_by('created_at').first()
        self.assertEqual(old.status,'superseded')
        self.assertEqual(SmsChallenge.objects.filter(status='sent').count(),1)

    def test_provider_error_never_creates_an_accepted_login_code(self):
        with patch('customer.sms.available',return_value=True),patch('customer.sms.send',side_effect=RuntimeError('provider error')):
            response=self.post('request-code',{'phone':PHONE})
        self.assertEqual(response.status_code,503)
        self.assertNotIn('challenge_id',response.json())
        self.assertEqual(SmsChallenge.objects.get().status,'failed')
        self.assertEqual(CustomerProfile.objects.count(),0)

    def test_anonymous_and_employee_cookies_do_not_authorize_customer_records(self):
        self.client.cookies['xuming_admin_dev']='an-employee-session'
        self.assertEqual(self.client.get('/api/customer/records').status_code,401)
        self.assertEqual(self.save().status_code,401)
        for path in ('/api/staff','/api/overview','/api/login','/backoffice/settings.py'):
            self.assertEqual(self.client.get(path).status_code,404)
        self.assertNotIn('backoffice_staffprofile',connection.introspection.table_names())

    def test_csrf_is_required_and_wrong_origin_rejected(self):
        client=Client(enforce_csrf_checks=True)
        self.assertEqual(self.post('request-code',{'phone':PHONE},client).status_code,403)
        token=client.get('/api/customer/session').json()['csrf']
        response=client.post('/api/customer/request-code',data=json.dumps({'phone':PHONE}),content_type='application/json',HTTP_X_CSRFTOKEN=token,HTTP_ORIGIN='https://evil.invalid')
        self.assertEqual(response.status_code,403)

    def test_save_requires_explicit_consent_and_ignores_no_purchase_flags(self):
        self.sign_in()
        request={'request_key':str(uuid.uuid4()),'input':VALID,'consent':False}
        self.assertEqual(self.post('records/save',request).status_code,400)
        request['consent']=True; request['paid']=True
        self.assertEqual(self.post('records/save',request).status_code,400)
        self.assertEqual(ServiceRecord.objects.count(),0)

    def test_record_is_encrypted_idempotent_and_retrievable(self):
        self.sign_in(); key=str(uuid.uuid4())
        first=self.save(key); self.assertEqual(first.status_code,201)
        record=first.json()['record']; row=ServiceRecord.objects.get()
        self.assertNotIn(b'birthDate',bytes(row.encrypted_report))
        self.assertNotIn('林'.encode(),bytes(row.encrypted_report))
        self.assertEqual(self.save(key).json()['record']['id'],record['id'])
        self.assertEqual(self.save(key,surname='李').status_code,409)
        fetched=self.client.get('/api/customer/records/'+record['id'])
        self.assertEqual(fetched.status_code,200)
        self.assertEqual(fetched.json()['report']['data']['surname'],'林')
        self.assertEqual(len(fetched.json()['report']['analysis']['bazi']['pillars']),4)
        self.assertEqual(fetched.json()['report']['kind'],'free_preview')
        self.assertIn('no-store',fetched['Cache-Control'])
        self.assertEqual(ServiceRecord.objects.count(),1)

    def test_saved_rename_preserves_original_report_and_correct_scenario(self):
        self.sign_in()
        response = self.save(purpose='rename',mode='born',dueDate='',birthDate='1998-08-13',birthTime='13:48',currentName='林景和')
        self.assertEqual(response.status_code,201)
        report = self.client.get('/api/customer/records/'+response.json()['record']['id']).json()['report']
        self.assertEqual(report['analysis']['workflow']['id'],'rename')
        self.assertEqual(report['analysis']['purpose'],'改名方案')
        self.assertEqual(report['analysis']['name_review']['full_name'],'林景和')
        self.assertTrue(all(row['name']!='林景和' for row in report['candidates']))
        self.assertNotIn('林景和'.encode(),bytes(ServiceRecord.objects.get().encrypted_report))

    def test_saved_civil_report_allows_missing_city(self):
        self.sign_in()
        response = self.save(place='')
        self.assertEqual(response.status_code, 201)
        report = self.client.get('/api/customer/records/'+response.json()['record']['id']).json()['report']
        self.assertEqual(report['data']['place'], '')
        self.assertFalse(report['analysis']['bazi']['time_correction']['applied'])

    def test_saved_solar_report_resolves_birth_city_once(self):
        self.sign_in()
        response = self.save(place='臺北市', timeBasis='apparent_solar')
        self.assertEqual(response.status_code, 201)
        report = self.client.get('/api/customer/records/'+response.json()['record']['id']).json()['report']
        time = report['analysis']['bazi']['time_correction']
        self.assertEqual(report['analysis']['zone'], 'Asia/Taipei')
        self.assertEqual(time['longitude'], 121.57)
        self.assertEqual(time['location']['coordinate_source'], 'city_centre')
        self.assertEqual(time['location']['label'], '台北')

    def test_save_rejects_mixed_flows_and_missing_current_name(self):
        self.sign_in()
        for changes in ({'birthDate':'2000-01-01','birthTime':'12:00'},{'purpose':'rename','mode':'born','dueDate':'','birthDate':'2000-01-01','birthTime':'12:00'}):
            with self.subTest(changes=changes):
                self.assertEqual(self.save(**changes).status_code,400)
        self.assertEqual(ServiceRecord.objects.count(),0)

    def test_saved_literary_report_recomputes_and_preserves_quotes_constraints_and_numerology(self):
        self.sign_in()
        response=self.save(algorithm='literary_v3',requiredChars='安',tabooChars='宁',numerologyMode='strict',surnameReading='lín')
        self.assertEqual(response.status_code,201)
        report=self.client.get('/api/customer/records/'+response.json()['record']['id']).json()['report']
        self.assertEqual(report['analysis']['algorithm'],'literary_v3')
        self.assertEqual(report['analysis']['corpus']['character_records'],3636)
        self.assertEqual(report['data']['requiredChars'],'安')
        self.assertTrue(all('安' in x['given'] and '宁' not in x['given'] and x['numerology']['strict_pass'] for x in report['candidates']))
        self.assertTrue(all(x['citations'] for x in report['candidates']))
        self.assertNotIn('安'.encode(),bytes(ServiceRecord.objects.get().encrypted_report))

    def test_literary_filter_conflicts_cannot_create_a_saved_record(self):
        self.sign_in()
        response=self.save(algorithm='literary_v3',requiredChars='安',tabooChars='安')
        self.assertEqual(response.status_code,400)
        self.assertEqual(ServiceRecord.objects.count(),0)

    def test_saved_report_preserves_reference_rule_and_new_evidence(self):
        self.sign_in()
        response=self.save(elementPreference='水',honorParents='true',parents='安',timeBasis='apparent_solar',longitude='120.16',locationId='hangzhou')
        self.assertEqual(response.status_code,201)
        report=self.client.get('/api/customer/records/'+response.json()['record']['id']).json()['report']
        self.assertEqual(report['data']['elementPreference'],'水')
        self.assertEqual(report['data']['honorParents'],'true')
        self.assertTrue(report['analysis']['bazi']['time_correction']['applied'])
        self.assertEqual(report['data']['longitude'],'120.16')
        self.assertEqual(report['analysis']['mingli']['classical_source_status'],'text_checked')
        self.assertEqual(report['analysis']['source_audit']['framework_status'],'text_checked')
        self.assertEqual(len(report['analysis']['traditional']['relationships']['pairs']),28)
        self.assertEqual(report['analysis']['naming_reference']['element'],'水')
        self.assertIn('polarity_counts',report['analysis']['traditional'])
        self.assertIn('arithmetic',report['analysis']['gua'])
        self.assertTrue(all(n['ranking']['version']=='naming-match-v2' for n in report['candidates']))

    def test_other_customer_cannot_list_retrieve_or_delete_record(self):
        self.sign_in(); record=self.save().json()['record']['id']
        self.post('logout',{}); self.sign_in('13900008000')
        self.assertEqual(self.client.get('/api/customer/records').json()['records'],[])
        self.assertEqual(self.client.get('/api/customer/records/'+record).status_code,404)
        self.assertEqual(self.post('records/'+record+'/delete',{}).status_code,404)
        self.assertEqual(ServiceRecord.objects.count(),1)

    def test_deleted_record_cannot_be_restored_by_replaying_old_save(self):
        self.sign_in(); key=str(uuid.uuid4())
        record=self.save(key).json()['record']['id']
        self.assertEqual(self.post('records/'+record+'/delete',{}).status_code,200)
        self.assertEqual(self.save(key).status_code,410)
        self.assertEqual(ServiceRecord.objects.count(),0)

    @override_settings(REPORT_LIMIT=1)
    def test_quota_delete_and_expiry(self):
        self.sign_in(); record=self.save().json()['record']['id']
        self.assertEqual(self.save().status_code,409)
        self.assertEqual(self.post('records/'+record+'/delete',{}).status_code,200)
        another=self.save().json()['record']['id']
        ServiceRecord.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.client.get('/api/customer/records/'+another).status_code,404)
        self.assertEqual(self.client.get('/api/customer/records').json()['records'],[])
        call_command('purge_customer_data',stdout=StringIO())
        self.assertEqual(ServiceRecord.objects.count(),0)

    @override_settings(SESSION_COOKIE_SECURE=True)
    def test_logout_and_customer_cookie_flags(self):
        self.sign_in()
        session=self.client.get('/api/customer/session')
        self.assertIn('no-store',session['Cache-Control'])
        cookie=self.client.cookies['xuming_customer_dev']
        self.assertTrue(cookie['httponly']); self.assertTrue(cookie['secure']); self.assertEqual(cookie['samesite'],'Strict')
        self.assertEqual(cookie['path'],'/api/customer/')
        self.post('logout',{})
        self.assertEqual(self.client.get('/api/customer/records').status_code,401)

    @override_settings(SMS_SECRET_ID='test-id',SMS_SECRET_KEY='test-key',SMS_APP_ID='test-app',SMS_SIGN_NAME='测试签名',SMS_TEMPLATE_ID='test-template')
    def test_tencent_adapter_uses_fixed_endpoint_and_approved_template_shape(self):
        from . import sms
        with patch('tencentcloud.sms.v20210111.sms_client.SmsClient') as factory:
            factory.return_value.SendSms.return_value=SimpleNamespace(SendStatusSet=[SimpleNamespace(Code='Ok')])
            sms.send('+86'+PHONE,CODE)
            request=factory.return_value.SendSms.call_args.args[0]
            self.assertEqual(request.PhoneNumberSet,['+86'+PHONE])
            self.assertEqual(request.TemplateParamSet,[CODE,'5'])
            self.assertEqual(factory.call_args.args[2].httpProfile.endpoint,'sms.tencentcloudapi.com')
