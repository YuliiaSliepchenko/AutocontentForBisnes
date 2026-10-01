from io import BytesIO

from PIL import Image


TOOLS = {'get_project', 'save_brand', 'create_carousel', 'get_script', 'approve_script',
         'edit_script', 'generate_cover_options', 'select_cover', 'generate_next_slide',
         'edit_slide', 'get_slide', 'get_project_status'}


def rpc(client, method, params=None, ident=1):
    response = client.post('/mcp', headers={'Accept': 'application/json, text/event-stream'},
                           json={'jsonrpc': '2.0', 'id': ident, 'method': method, 'params': params or {}})
    assert response.status_code == 200, response.text
    return response.json()


def test_health_ui_and_validation(client):
    assert client.get('/health').json() == {'status': 'ok', 'service': 'autocontent', 'provider': 'mock'}
    assert 'AutoContent' in client.get('/').text
    assert client.get('/static/app.js').status_code == 200
    assert client.get('/openapi.json').status_code == 200
    assert client.post('/api/carousels', json={}).status_code == 422
    assert client.get('/api/projects/missing').status_code == 404
    assert client.get('/api/assets/missing').status_code == 404


def test_rest_roundtrip(client, brand_input, brief):
    body = {'request_id': 'brand', 'brand': brand_input.model_dump(mode='json')}
    brand = client.post('/api/brands', json=body).json()['brand']
    assert client.post('/api/brands', json=body).json()['brand'] == brand
    result = client.post('/api/carousels', json={'request_id': 'create', 'brand_id': brand['id'], 'brief': brief.model_dump()}).json()
    pid = result['project']['id']
    def post(path, key, **extra):
        return client.post(f'/api/projects/{pid}/{path}', json={'request_id':key,'expected_revision':result['project']['revision'],**extra})
    assert post('covers/generate', 'forbidden').status_code == 409
    result = post('script/approve', 'approve').json()
    result = post('covers/generate', 'covers').json()
    assert result['project']['state'] == 'COVER_SELECTION'
    result = post('covers/select', 'select', choice=2).json()
    assert result['project']['current_slide'] == 2
    result = post('slides/edit', 'edit', slide_number=2, changes='Більше контрасту').json()
    assert len(client.get(f'/api/projects/{pid}/slides/2').json()['versions']) == 2
    assert client.get(f'/api/projects/{pid}/slides/3').status_code == 404
    assert client.get(f'/api/projects/{pid}/script?version=1').json()['approved']
    assert client.get(f'/api/projects/{pid}/status').json()['project']['current_slide'] == 2
    assert client.get(f"/api/jobs/{result['job_id']}").json()['status'] == 'succeeded'
    image = client.get(result['slides'][-1]['url'])
    assert image.headers['content-type'] == 'image/png'
    assert Image.open(BytesIO(image.content)).size == (1080,1350)


def test_mcp_streamable_http_shared_with_rest(client, project):
    init = rpc(client, 'initialize', {'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'test','version':'1'}})
    assert init['result']['serverInfo']['name'] == 'AutoContent'
    listed = rpc(client, 'tools/list')['result']['tools']
    assert {t['name'] for t in listed} == TOOLS
    pid = project['project']['id']
    read = rpc(client, 'tools/call', {'name':'get_project','arguments':{'project_id':pid}})['result']
    assert not read.get('isError')
    assert read['structuredContent']['project']['state'] == 'SCRIPT_REVIEW'
    bad = rpc(client, 'tools/call', {'name':'generate_cover_options','arguments':{'project_id':pid,'command':{'request_id':'early','expected_revision':1}}})['result']
    assert bad['isError']
    approved = rpc(client, 'tools/call', {'name':'approve_script','arguments':{'project_id':pid,'command':{'request_id':'approve','expected_revision':1}}})['result']
    assert not approved.get('isError')
    assert client.get(f'/api/projects/{pid}').json()['project']['state'] == 'COVERS_PENDING'
    # A new stateless request sees the same durable state, no session id required.
    status = rpc(client, 'tools/call', {'name':'get_project_status','arguments':{'project_id':pid}})['result']
    assert status['structuredContent']['project']['revision'] == 2
    # Replay through the other transport must not apply the action twice.
    replay = client.post(f'/api/projects/{pid}/script/approve', json={'request_id':'approve','expected_revision':1})
    assert replay.status_code == 200
    assert replay.json()['project']['revision'] == 2


def test_full_carousel_via_mcp(client, brand_input, brief):
    def call(name, arguments):
        output = rpc(client, 'tools/call', {'name': name, 'arguments': arguments})['result']
        assert not output.get('isError'), output
        return output['structuredContent']
    saved = call('save_brand', {'command': {'request_id':'mcp-brand','brand':brand_input.model_dump(mode='json')}})
    result = call('create_carousel', {'command': {'request_id':'mcp-create','brand_id':saved['brand']['id'],'brief':brief.model_dump()}})
    pid = result['project']['id']
    def change(tool, key, **extra):
        return call(tool, {'project_id':pid,'command':{'request_id':key,'expected_revision':result['project']['revision'],**extra}})
    script = call('get_script', {'project_id':pid})
    script['slides'][0]['title'] = 'Edited via MCP'
    result = change('edit_script', 'mcp-edit-script', slides=script['slides'])
    result = change('approve_script', 'mcp-approve')
    result = change('generate_cover_options', 'mcp-covers')
    result = change('select_cover', 'mcp-select', choice=1)
    result = change('edit_slide', 'mcp-edit-slide', slide_number=2, changes='More space')
    assert len(call('get_slide', {'project_id':pid,'slide_number':2})['versions']) == 2
    for current in range(2,6):
        result = change('generate_next_slide', f'mcp-next-{current}', confirmed_slide=current)
    assert result['project']['state'] == 'COMPLETED'
    assert all(s['script_version'] == 2 for s in result['slides'])
    assert client.get(f'/api/projects/{pid}').json()['project']['state'] == 'COMPLETED'
