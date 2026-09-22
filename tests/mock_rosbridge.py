"""功能说明：仅用于本地联调的 rosbridge 协议替身，不连接或控制真实机器人。"""
import asyncio
import base64
import json
import math
import struct
import time
from pathlib import Path

from websockets.asyncio.server import serve

TOPICS = {'/ndt_pose':'geometry_msgs/PoseStamped','/display/tf':'tf2_msgs/TFMessage','/tf':'tf2_msgs/TFMessage','/battery':'sensor_msgs/BatteryState','/odometry/filtered':'nav_msgs/Odometry','/livox/lidar':'sensor_msgs/PointCloud2','/score':'std_msgs/Float64'}


async def client(ws):
    """处理订阅和 rosapi 查询；所有控制下发只记录在测试目录。"""
    subscriptions = set()

    async def stream():
        while True:
            t=time.time()
            position={'x':math.sin(t*.3)*2,'y':math.cos(t*.3)*2,'z':.35}
            q={'x':0,'y':0,'z':math.sin(t*.15),'w':math.cos(t*.15)}
            header={'frame_id':'map','stamp':{'sec':int(t),'nanosec':int(t%1*1e9)}}
            pose={'position':position,'orientation':q}
            cloud=base64.b64encode(b''.join(struct.pack('<fff',x*.2,y*.2,0) for x in range(-15,16) for y in range(-15,16))).decode()
            messages={'/ndt_pose':{'header':header,'pose':pose},'/battery':{'percentage':.73},'/score':{'data':.91},'/odometry/filtered':{'header':header,'pose':{'pose':pose},'twist':{'twist':{'linear':{'x':.6,'y':0,'z':0}}}},'/livox/lidar':{'header':header,'height':1,'width':961,'fields':[{'name':n,'offset':i*4,'datatype':7,'count':1} for i,n in enumerate(['x','y','z'])],'is_bigendian':False,'point_step':12,'row_step':11532,'is_dense':True,'data':cloud}}
            tf={'transforms':[{'header':header,'child_frame_id':'base_link','transform':{'translation':position,'rotation':q}}]}
            messages.update({'/tf':tf,'/display/tf':tf})
            for topic in list(subscriptions):
                if topic in messages:
                    await ws.send(json.dumps({'op':'publish','topic':topic,'msg':messages[topic]}))
            await asyncio.sleep(.1)

    task=asyncio.create_task(stream())
    try:
        async for raw in ws:
            msg=json.loads(raw)
            if msg['op']=='subscribe':subscriptions.add(msg['topic'])
            elif msg['op']=='unsubscribe':subscriptions.discard(msg['topic'])
            elif msg['op']=='call_service':
                values={'topics':list(TOPICS),'types':list(TOPICS.values()),'typedefs':[],'names':[],'value':'null'}
                await ws.send(json.dumps({'op':'service_response','id':msg.get('id'),'service':msg['service'],'values':values,'result':True}))
            elif msg['op']=='publish':
                path=Path(__file__).resolve().parents[1]/'output_qa'/'commands.jsonl'
                path.parent.mkdir(exist_ok=True)
                with path.open('a',encoding='utf-8') as log:log.write(json.dumps(msg,ensure_ascii=False)+'\n')
    finally:
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)


async def main():
    async with serve(client,'127.0.0.1',9099):
        print('本地测试 rosbridge: ws://127.0.0.1:9099',flush=True)
        await asyncio.Future()


if __name__=='__main__':
    asyncio.run(main())
