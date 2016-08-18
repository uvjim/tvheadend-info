from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from operator import itemgetter
import smtplib
import urllib
import urllib2
import json
import datetime, time
import sys
import getopt
import re

class Mail:
    def __init__(self, smtpserver, smtpport, smtpuser, smtppwd):
        self.smtpuser = smtpuser
        self.smtppwd = smtppwd
        self.server = smtplib.SMTP(smtpserver, smtpport)
        self.mail = MIMEMultipart('alternative')
        self.mail['Subject'] = "TVHeadend script results"

    def send(self, body, toaddress, fromaddress):
        self.mail['To'] = toaddress
        self.mail['From'] = fromaddress
        self.mail.attach(MIMEText(body, 'html'))
        self.server.starttls()
        self.server.login(self.smtpuser, self.smtppwd)
        self.server.sendmail(self.mail['From'], self.mail['To'], self.mail.as_string())
        self.server.quit()

    @staticmethod
    def getDateTimeFromEpoch(epoch):
        return datetime.datetime.fromtimestamp(epoch).strftime('%Y-%m-%d %H:%M:%S')

class Rest:
    def __init__(self, server, user, password):
        if user and password:
            self.user = user
            self.password = password
            self.server = server
        else:
            if not user or not password:
                sys.exit("Must supply a user and password")

    def getURL(self, api, creds=False):
        ret = 'http://{}:9981{}'.format(self.server, api) if not creds else 'http://{}:{}@{}:9981{}'.format(self.user, self.password, self.server, api)
        return ret

    def fetch(self, url, data=None):
        auth_handler = urllib2.HTTPDigestAuthHandler()
        auth_handler.add_password(realm='tvheadend', uri=url, user=self.user, passwd=self.password)
        opener = urllib2.build_opener(auth_handler)
        urllib2.install_opener(opener)
        return urllib2.urlopen(url, data)

class Services:
    DVBServiceType = {1: 'SD Channel (MPEG2)', 2: 'Radio', 12: 'Data Channel', 22: 'SD Channel (H.264)', 25: 'HD Channel'}

    def __init__(self, restservice):
        self.services = None
        self.rest = restservice

    def get(self):
        api = '/api/service/list'
        r = self.rest.fetch(self.rest.getURL(api))
        self.services = json.loads(r.read())

    def getNew(self, offsetDays):
        ret = []
        if self.services is None:
            self.get()
        if not self.services is None:
            for s in self.services['entries']:
                p = s['params']
                svc = None
                for idx, val in enumerate(p):
                    if val['id'] == 'created' and 'value' in val:
                        c = val['value']
                        e = int(time.time())
                        o = e - (offsetDays * 24 * 60 * 60)
                        if c > o: #new service so get the name and when it was found
                            name = [val['value'] for idx, val in enumerate(p) if val['id'] == 'svcname' and 'value' in val]
                            if len(name):
                                svctype = [val['value'] for idx, val in enumerate(p) if val['id'] == 'dvb_servicetype' and 'value' in val]
                                svctype = Services.DVBServiceType[svctype[0]] if Services.DVBServiceType.has_key(svctype[0]) else svctype[0]
                                multiplex = [val['value'] for idx, val in enumerate(p) if val['id'] == 'multiplex' and 'value' in val][0]
                                if '.m3u - ' in multiplex:
                                    svctype += ' (from playlist)'
                                mapdata = urllib.urlencode({'node': json.dumps({'services': [s['uuid']], 'encrypted': False, 'merge_same_name': True}, separators=(',', ':'))})
                                disabledata = urllib.urlencode({'node': json.dumps([{'enabled': False, 'uuid': s['uuid']}], separators=(',', ':'))})
                                svc = (name[0], svctype, Mail.getDateTimeFromEpoch(c), (self.rest.getURL('/api/service/mapper/save', creds=True), mapdata), (self.rest.getURL('/api/idnode/save', creds=True), disabledata))
                        break
                if svc:
                    ret.append(svc)
        if len(ret) == 0:
            ret = None
        else:
            ret = sorted(ret, key=itemgetter(1), reverse=True)
        return ret

    def getBlank(self):
        ret = []
        if self.services is None:
            self.get()
        if not self.services is None:
            for s in self.services['entries']:
                p = s['params']
                svc = None
                for idx, val in enumerate(p):
                    if val['id'] == 'svcname' and not 'value' in val:
                        ret.append(s['uuid'])
                        break
        return ret

    def delete(self, uuid):
        api = '/api/idnode/delete'
        r = self.rest.fetch(self.rest.getURL(api), urllib.urlencode({'uuid': uuid}))

class DVR:
    def __init__(self, restservice):
        self.rest = restservice

    def getFailed(self):
        ret = False
        api = '/api/dvr/entry/grid_failed'
        ret = self.rest.fetch(self.rest.getURL(api))
        ret = json.loads(ret.read()) if ret else False
        for idx, r in enumerate(ret['entries']):
            if r['status'].lower() == 'user request':
                ret['entries'][idx]['action_movefinished'] = "{}?{}".format(self.rest.getURL('/api/dvr/entry/move/finished', True), urllib.urlencode({'uuid': json.dumps([r['uuid']])}))
        return ret

def main(argv):
    settings = {}
    settings['days'] = 1
    settings['clean'] = False
    settings['dvrfailed'] = False
    mansettings = ['smtp-server', 'smtp-port', 'smtp-user', 'smtp-pwd', 'send-to', 'send-from', 'tvh-server', 'tvh-user', 'tvh-pwd']
    body = None

    #-- process the arguments --#
    try:
        opts, args = getopt.getopt(argv, 'cd:f', ['clean', 'days=', 'dvrfailed', 'smtp-server=', 'smtp-port=', 'smtp-user=', 'smtp-pwd=', 'send-to=', 'send-from=', 'tvh-server=', 'tvh-user=', 'tvh-pwd='])
    except getopt.GetoptError:
        sys.exit('Invalid arguments')

    for opt, arg in opts:
        if opt in ('-d', '--days'):
            settings['days'] = int(arg)
        if opt in ('-c', '--clean'):
            settings['clean'] = True
        if opt in ('-f', '--dvrfailed'):
            settings['dvrfailed'] = True
        if opt in ('--smtp-server'):
            settings['smtp-server'] = arg
        if opt in ('--smtp-port'):
            settings['smtp-port'] = int(arg)
        if opt in ('--smtp-user'):
            settings['smtp-user'] = arg
        if opt in ('--smtp-pwd'):
            settings['smtp-pwd'] = arg
        if opt in ('--send-from'):
            settings['send-from'] = arg
        if opt in ('--send-to'):
            settings['send-to'] = arg
        if opt in ('--tvh-server'):
            settings['tvh-server'] = arg
        if opt in ('--tvh-user'):
            settings['tvh-user'] = arg
        if opt in ('--tvh-pwd'):
            settings['tvh-pwd'] = arg

    regexMan = re.compile("^(send|smtp|tvh)-.*")
    manargs = filter(regexMan.search, settings)
    blnContinue = True if len(manargs) == len(mansettings) else False
    if not blnContinue:
        sys.exit('You must provide SMTP details including from and to addresses and a TVH server')

    tvhRest = Rest(settings['tvh-server'], settings['tvh-user'], settings['tvh-pwd'])
    tvhServices = Services(tvhRest)
    tvhNewServices = tvhServices.getNew(settings['days'])
    if tvhNewServices:
        body = "<h1 style='text-decoration: underline; font-size: 1.3em; margin: 0px 4px 0px 0px;'>New Service</h1>"
        body += "<p style='padding: 0px; margin: 10px 0px;'>In the last {} days the following services were found: -</p>".format(settings['days'])
        body += "<table style='border-collapse: collapse; width: 100%; border: 1px solid black;'>"
        body += "<tr style='background-color: #4444DE; color: white;'><th style='padding: 4px 2px; border: 1px solid black;'>Service Name</th><th style='padding: 4px 2px; border: 1px solid black;'>Type</th><th style='padding: 4px 2px; border: 1px solid black;'>Found</th><th style='padding: 4px 2px; border: 1px solid black;'>Actions</th></tr>"
        for idx, s in enumerate(tvhNewServices):
            rowStyle = " style='background-color: #DEDEDE;'" if idx % 2 == 0 else ''
            body += ''.join("<tr{}><td style='padding: 4px 2px; border: 1px solid black;'>{}</td><td style='text-align: center; padding: 4px 2px; border: 1px solid black;'>{}</td><td style='text-align: center; padding: 4px 2px; border: 1px solid black;'>{}</td><td style='text-align: center; padding: 4px 2px; border: 1px solid black;'><a href='{}?{}'>disable</a>&nbsp;&nbsp;<a href='{}?{}'>map</a></td></tr>".format(rowStyle, s[0], s[1], s[2], s[4][0], s[4][1], s[3][0], s[3][1]))
        body += "</table>"

    if settings['clean']:
        b = tvhServices.getBlank()
        if b:
            for s in b:
                tvhServices.delete(s)
            if not body:
                body = ""
            body += "<h1 style='text-decoration: underline; font-size: 1.3em; margin: 0px 4px 0px 0px;'>Empty Services</h1>"
            body += "<p>{} were cleaned</p>".format(len(b))

    if settings['dvrfailed']:
        tvhDVR = DVR(tvhRest)
        f = tvhDVR.getFailed()
        if f['total']:
            if not body:
                body = ""
            body = "<h1 style='text-decoration: underline; font-size: 1.3em; margin: 0px 4px 0px 0px;'>Failed Recordings</h1>"
            body += "<p style='padding: 0px; margin: 10px 0px;'>The following {} failed recordings were found: -</p>".format(f['total'])
            body += "<table style='border-collapse: collapse; width: 100%; border: 1px solid black;'>"
            body += "<tr style='background-color: #4444DE; color: white;'><th style='padding: 4px 2px; border: 1px solid black;'>Display Name</th><th style='padding: 4px 2px; border: 1px solid black;'>Channel</th><th style='padding: 4px 2px; border: 1px solid black;'>Scheduled Start</th><th style='padding: 4px 2px; border: 1px solid black;'>Scheduled Stop</th><th style='padding: 4px 2px; border: 1px solid black;'>Status</th><th style='padding: 4px 2px; border: 1px solid black;'>Actions</th></tr>"
            for idx, r in enumerate(f['entries']):
                rowStyle = " style='background-color: #DEDEDE;'" if idx % 2 == 0 else ''
                body += ''.join("<tr{}><td style='padding: 4px 2px; border: 1px solid black;'>{}</td><td style='text-align: center; padding: 4px 2px; border: 1px solid black;'>{}</td><td style='text-align: center; padding: 4px 2px; border: 1px solid black;'>{}</td><td style='text-align: center; padding: 4px 2px; border: 1px solid black;'>{}</td><td style='padding: 4px 2px; border: 1px solid black;'>{}</td><td style='text-align: center; padding: 4px 2px; border: 1px solid black;'><a href='{}'>{}</a></td></tr>".format(rowStyle, r['disp_title'], r['channelname'], Mail.getDateTimeFromEpoch(r['start_real']), Mail.getDateTimeFromEpoch(r['stop_real']), r['status'], r['action_movefinished'] if 'action_movefinished' in r else '', 'Move to finished' if 'action_movefinished' in r else ''))
            body += "</table>"

    if body:
        body = "<html><body>{}</body></html>".format(body)
        m = Mail(settings['smtp-server'], settings['smtp-port'], settings['smtp-user'], settings['smtp-pwd'])
        m.send(body, settings['send-to'], settings['send-from'])

if __name__ == "__main__":
   main(sys.argv[1:])