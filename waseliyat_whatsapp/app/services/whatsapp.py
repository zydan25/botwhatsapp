import requests


class WhatsAppClient:
    def __init__(self, session):
        self.session = session

    def _get(self, action, timeout=10, params=None):
        try:
            r = requests.get(self.session.api_url(action), timeout=timeout, params=params)
            return self._response(r)
        except requests.RequestException as exc:
            return {'ok': False, 'error': str(exc), 'status_code': 0}

    def _post(self, action, timeout=20, json_body=None, files=None, data=None):
        try:
            r = requests.post(self.session.api_url(action), timeout=timeout, json=json_body, files=files, data=data)
            return self._response(r)
        except requests.RequestException as exc:
            return {'ok': False, 'error': str(exc), 'status_code': 0}

    @staticmethod
    def _response(response):
        try:
            payload = response.json()
        except ValueError:
            payload = {'raw': response.text}
        ok = response.ok and payload.get('success', True) is not False
        return {
            'ok': ok,
            'status_code': response.status_code,
            'data': payload.get('data', payload),
            'payload': payload,
            'error': payload.get('message') or payload.get('error'),
        }

    def status(self, timeout=10):
        return self._get('status', timeout=timeout)

    def connect(self):
        return self._post('connect', json_body={}, timeout=25)

    def disconnect(self):
        return self._post('disconnect', json_body={}, timeout=20)

    def logout(self):
        return self._post('logout', json_body={}, timeout=20)

    def qr(self):
        return self._get('qr', timeout=10)

    def qr_image(self):
        try:
            r = requests.get(self.session.api_url('qr-image'), timeout=15)
            if not r.ok:
                return {'ok': False, 'error': f'HTTP {r.status_code}', 'content_type': r.headers.get('Content-Type')}
            return {'ok': True, 'bytes': r.content, 'content_type': r.headers.get('Content-Type', 'image/png')}
        except requests.RequestException as exc:
            return {'ok': False, 'error': str(exc)}

    def send(self, phone, message, media_file=None):
        data = {'phoneNumber': phone, 'message': message}
        files = None
        opened = None
        try:
            if media_file:
                opened = open(media_file, 'rb')
                files = {'media': opened}
            return self._post('send', timeout=40, data=data, files=files)
        finally:
            if opened:
                opened.close()

    def messages(self, limit=50, offset=0):
        return self._get('messages', params={'limit': min(int(limit), 100), 'offset': max(int(offset), 0)})

    def errors(self, limit=25):
        return self._get('errors', params={'limit': min(int(limit), 100)})

    def notifications(self, limit=50):
        return self._get('notifications', params={'limit': min(int(limit), 100)})

    def set_api_url(self, api_base_url):
        return self._post('api-url', json_body={'apiBaseUrl': api_base_url}, timeout=15)
