import { connect } from 'cloudflare:sockets';

const FALLBACK_URI = 'www.speedtest.net';

export default {
    async fetch(request, env, ctx) {
        try {
            const upgradeHeader = request.headers.get('Upgrade');
            if (!upgradeHeader || upgradeHeader !== 'websocket') {
                const url = new URL(request.url);
                url.hostname = FALLBACK_URI;
                url.protocol = 'https:';
                return fetch(new Request(url, request));
            }

            const webSocketPair = new WebSocketPair();
            const [client, server] = Object.values(webSocketPair);
            server.accept();

            let tcpConn = null;
            let isHandshakeComplete = false;
            const appSecretHex = (env.APP_TOKEN || '219f4d83-59e0-457f-b596-6a7e87dbc971').replace(/-/g, '');

            server.addEventListener('message', (event) => {
                const payloadBuffer = event.data;

                if (!isHandshakeComplete) {
                    isHandshakeComplete = true;
                    try {
                        const {
                            valid,
                            targetHost,
                            targetPort,
                            dataOffset,
                            versionCode
                        } = parseAuthProtocol(payloadBuffer, appSecretHex);

                        if (!valid) throw new Error('Auth failed');

                        tcpConn = connect({ hostname: targetHost, port: targetPort });
                        // 忽略握手异常
                        tcpConn.closed.catch(() => { });

                        const writer = tcpConn.writable.getWriter();
                        server.addEventListener('close', () => tcpConn.close());
                        server.addEventListener('error', () => tcpConn.close());

                        // 透传首包剩余数据
                        writer.write(payloadBuffer.slice(dataOffset));
                        writer.releaseLock();

                        // 返回握手确认响应
                        server.send(new Uint8Array([versionCode[0], 0]));

                        // 建立持续流转接
                        tcpConn.readable.pipeTo(new WritableStream({
                            write(chunk) { server.send(chunk); },
                            close() { server.close(); },
                            abort() { server.close(); }
                        }));

                    } catch (err) {
                        server.close();
                    }
                    return;
                }

                if (tcpConn) {
                    const writer = tcpConn.writable.getWriter();
                    writer.write(payloadBuffer);
                    writer.releaseLock();
                }
            });

            return new Response(null, { status: 101, webSocket: client });
        } catch (err) {
            return new Response('Service Error', { status: 500 });
        }
    }
};

function parseAuthProtocol(buffer, secretHex) {
    if (buffer.byteLength < 24) return { valid: false };

    const versionCode = new Uint8Array(buffer.slice(0, 1));
    const tokenBytes = new Uint8Array(buffer.slice(1, 17));
    const tokenHex = [...tokenBytes].map((b) => b.toString(16).padStart(2, '0')).join('');

    if (tokenHex !== secretHex) return { valid: false };

    const optLen = new Uint8Array(buffer.slice(17, 18))[0];
    const portIdx = 18 + optLen + 1;
    const targetPort = new DataView(buffer.slice(portIdx, portIdx + 2)).getUint16(0);

    let addrIdx = portIdx + 2;
    const addrType = new Uint8Array(buffer.slice(addrIdx, addrIdx + 1))[0];

    let addrLen = 0;
    let targetHost = '';

    if (addrType === 1) {
        addrLen = 4;
        targetHost = new Uint8Array(buffer.slice(addrIdx + 1, addrIdx + 1 + addrLen)).join('.');
    } else if (addrType === 2) {
        addrLen = new Uint8Array(buffer.slice(addrIdx + 1, addrIdx + 2))[0];
        addrIdx += 1;
        targetHost = new TextDecoder().decode(buffer.slice(addrIdx + 1, addrIdx + 1 + addrLen));
    } else if (addrType === 3) {
        addrLen = 16;
        const view = new DataView(buffer.slice(addrIdx + 1, addrIdx + 1 + addrLen));
        const parts = [];
        for (let i = 0; i < 8; i++) parts.push(view.getUint16(i * 2).toString(16));
        targetHost = parts.join(':');
    } else {
        return { valid: false };
    }

    return {
        valid: true,
        targetHost,
        targetPort,
        dataOffset: addrIdx + 1 + addrLen,
        versionCode
    };
}
