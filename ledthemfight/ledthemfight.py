#!/usr/bin/env python3

import argparse, sys, os, json, urllib.parse, urllib.request, signal, threading, time
from datetime import datetime
from multiprocessing import Process, Queue
from http.server import HTTPServer, SimpleHTTPRequestHandler

conf_file = '/etc/ledthemfight.conf'
conf = None
to_led_driver = Queue()
to_web_server = Queue()
manual_override = False
solar_times = {}

def conf_save():
    dat = json.dumps(conf, indent=2)
    open(conf_file, 'w').write(dat)

def conf_push():
    to_led_driver.put(['/initial_setup', conf])

def fetch_solar_times():
    try:
        lat = conf.get('latitude')
        lon = conf.get('longitude')
        if not lat or not lon:
            with urllib.request.urlopen('https://ipinfo.io/json', timeout=5) as r:
                geo = json.loads(r.read().decode())
            lat_str, lon_str = geo.get('loc', '59.9139,10.7522').split(',')
            lat, lon = float(lat_str), float(lon_str)
            conf['latitude'] = lat
            conf['longitude'] = lon
            conf_save()
        today = datetime.now().strftime('%Y-%m-%d')
        offset = datetime.now().astimezone().strftime('%z')
        offset_fmt = offset[:3] + ':' + offset[3:]
        url = (f'https://api.met.no/weatherapi/sunrise/3.0/sun'
               f'?lat={lat}&lon={lon}&date={today}&offset={offset_fmt}')
        req = urllib.request.Request(url, headers={'User-Agent': 'ledthemfight/1.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        props = data['properties']
        solar_times['on'] = props['sunset']['time'][11:16]
        solar_times['off'] = props['sunrise']['time'][11:16]
        solar_times['date'] = today
        print(f'Solar: på (solnedgang) {solar_times["on"]}, av (soloppgang) {solar_times["off"]}', flush=True)
    except Exception as e:
        print(f'Solar fetch error: {e}', file=sys.stderr, flush=True)

def timer_loop():
    global manual_override
    fired = None
    while True:
        time.sleep(20)
        if not conf or not conf.get('timer_enabled') or not conf.get('set_up'):
            fired = None
            continue

        if conf.get('timer_mode') == 'solar':
            today = datetime.now().strftime('%Y-%m-%d')
            if solar_times.get('date') != today:
                fetch_solar_times()
            on_time = solar_times.get('on')
            off_time = solar_times.get('off')
        else:
            on_time = conf.get('timer_on')
            off_time = conf.get('timer_off')

        if not on_time or not off_time:
            continue

        now = datetime.now().strftime('%H:%M')
        if now == on_time and fired != ('on', now):
            fired = ('on', now)
            if manual_override:
                manual_override = False
                continue
            to_led_driver.put(['/button', ('brightness', 230)])
            to_led_driver.put(['/button', ('effect', 'Warm_White')])
        elif now == off_time and fired != ('off', now):
            fired = ('off', now)
            if manual_override:
                manual_override = False
                continue
            to_led_driver.put(['/button', ('stop', None)])
        elif now not in (on_time, off_time):
            fired = None

class MyHandler(SimpleHTTPRequestHandler):
    # set a short timeout since Python's http.server basic implementation
    # is not threaded and only accepts 1 blocking client at a time
    # (note: the timeout is implemented by StreamRequestHandler, parent
    # of BaseHTTPRequestHandler, parent of SimpleHTTPRequestHandler)
    timeout = 5

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory='www', **kwargs)

    def end_headers(self):
        # 'no-cache' means client CAN cache but must revalidate the cached
        # response every reuse, which is what we want as files often change
        # (eg. the sequence binary files)
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def parse_form(self):
        assert self.headers['Content-Type'] == \
                'application/x-www-form-urlencoded'
        cl = int(self.headers['Content-Length'])
        dat = self.rfile.read(cl).decode()
        return urllib.parse.parse_qs(dat)

    def parse_json(self):
        assert self.headers['Content-Type'] == 'application/json'
        cl = int(self.headers['Content-Length'])
        dat = self.rfile.read(cl).decode()
        return json.loads(dat)

    def write_data(self, data):
        self.wfile.write(data.encode())

    def get_data(self, data):
        to_led_driver.put(['/get', data])
        key, val = to_web_server.get()
        if key == '/state':
            resp = val
        else:
            self.send_error(500, f'{key}: {val}')
            return
        self.send_response(200)
        self.end_headers()
        self.write_data(json.dumps(resp) + '\n')

    def do_GET(self):
        if self.path == '/':
            if not conf['set_up']:
                self.send_response(302)
                self.send_header('Location', '/welcome.html')
                self.end_headers()
                return
            self.path = '/index.html'
        if self.path == '/get/timer':
            if conf.get('timer_mode') == 'solar' and not solar_times.get('on'):
                threading.Thread(target=fetch_solar_times, daemon=True).start()
            self.send_response(200)
            self.end_headers()
            self.write_data(json.dumps({
                'enabled': conf.get('timer_enabled', False),
                'mode': conf.get('timer_mode', 'manual'),
                'on': conf.get('timer_on', ''),
                'off': conf.get('timer_off', ''),
                'solar_on': solar_times.get('on', ''),
                'solar_off': solar_times.get('off', ''),
            }) + '\n')
            return
        if self.path.startswith('/get/'):
            return self.get_data(self.path[4:])
        # whitelist of URL paths
        if not self.path.startswith('/sequence/') and \
           self.path not in (
                '/brightness.svg',
                '/cash.js',
                '/index.html',
                '/main.css',
                '/main.js',
                '/welcome.html',
                ):
            return self.send_error(404)
        return super().do_GET()

    def do_POST(self):
        if self.path == '/initial_setup':
            form = self.parse_form()
            conf.update({
                'set_up': True,
                'name': form.get('name')[0],
                'nr_led_strings': int(form.get('nr_led_strings')[0]),
                'num_pixels': int(form.get('num_pixels')[0]),
                'inverted': 'inverted' in form,
                })
            conf_save()
            conf_push()
            self.send_response(303)
            self.send_header('Location', '/')
            self.end_headers()
        elif not conf['set_up']:
            self.send_error(500, 'Server is not set up')
        elif self.path == '/timer':
            j = self.parse_json()
            conf['timer_enabled'] = bool(j.get('enabled'))
            conf['timer_mode'] = j.get('mode', 'manual')
            conf['timer_on'] = j.get('on', '')
            conf['timer_off'] = j.get('off', '')
            conf_save()
            if conf['timer_mode'] == 'solar' and not solar_times.get('on'):
                threading.Thread(target=fetch_solar_times, daemon=True).start()
            self.send_response(200)
            self.end_headers()
        elif self.path not in ('/button',):
            self.send_error(404)
        else:
            global manual_override
            j = self.parse_json()
            if j.get('name') == 'effect' and j.get('value'):
                conf['timer_last_effect'] = j['value']
                conf_save()
            manual_override = True
            to_led_driver.put([self.path, (j['name'], j.get('value'))])
            self.send_response(200)
            self.end_headers()

def led_driver_process(to_led_driver, to_web_server):
    import worker_led
    worker_led.drive_led_forever(to_led_driver, to_web_server)

def sequence_generator_process():
    import worker_led
    worker_led.seqgen_forever()

def main_exit(signal_number, stack_frame):
    # Calling sys.exit() allows the process to terminate the daemon=True
    # child processes gracefully
    sys.exit(0)

def main():
    global conf
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--port', type=int, default=80)
    args = parser.parse_args()
    try:
        conf = json.load(open(conf_file))
        conf_push()
    except FileNotFoundError:
        conf = { 'set_up': False }
    signal.signal(signal.SIGTERM, main_exit)
    Process(target=led_driver_process, daemon=True,
            name='led_driver', args=(to_led_driver, to_web_server)).start()
    Process(target=sequence_generator_process, daemon=True,
            name='seqgen', args=()).start()
    threading.Thread(target=timer_loop, daemon=True, name='timer').start()
    if conf.get('timer_mode') == 'solar':
        threading.Thread(target=fetch_solar_times, daemon=True).start()
    # start web server
    HTTPServer.allow_reuse_address = True
    httpd = HTTPServer(('', args.port), MyHandler)
    print(f'Web server running on port {args.port}/tcp')
    httpd.serve_forever()

if __name__ == '__main__':
    main()
