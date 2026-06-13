#!/bin/sh
# ======= FILE: /usr/lib/lua/luci/view/web/index.htm ======= 
sed -i 's/>Wi-Fi名称</><%:Wi-Fi名称%></g' /usr/lib/lua/luci/view/web/index.htm
sed -i ':a;N;$!ba;s/>Wi-Fi密码： \n                                </><%:Wi-Fi密码：%> \n                                </g' /usr/lib/lua/luci/view/web/index.htm
sed -i 's/>连接设备数量 --</><%:连接设备数量 --%></g' /usr/lib/lua/luci/view/web/index.htm
sed -i 's/>设置</><%:设置%></g' /usr/lib/lua/luci/view/web/index.htm
sed -i ':a;N;$!ba;s/>Wi-Fi密码：\n                                </><%:Wi-Fi密码：%>\n                                </g' /usr/lib/lua/luci/view/web/index.htm
sed -i 's/>断开</><%:断开%></g' /usr/lib/lua/luci/view/web/index.htm
sed -i 's/'\''Mesh组网设备'\''/'\''<%:Mesh组网设备%>'\''/g' /usr/lib/lua/luci/view/web/index.htm
sed -i 's/'\''Wi-Fi名称：'\''/'\''<%:Wi-Fi名称：%>'\''/g' /usr/lib/lua/luci/view/web/index.htm
sed -i 's/'\''Wi-Fi密码: 未设置'\''/'\''<%:Wi-Fi密码: 未设置%>'\''/g' /usr/lib/lua/luci/view/web/index.htm
sed -i 's/'\''连接设备数量：'\''/'\''<%:连接设备数量：%>'\''/g' /usr/lib/lua/luci/view/web/index.htm
sed -i 's/'\''拨号成功'\''/'\''<%:拨号成功%>'\''/g' /usr/lib/lua/luci/view/web/index.htm
sed -i 's/"Mesh组网"/"<%:Mesh组网%>"/g' /usr/lib/lua/luci/view/web/index.htm
# ======= FILE: /usr/lib/lua/luci/view/web/apindex.htm ======= 
sed -i 's/>Wi-Fi名称</><%:Wi-Fi名称%></g' /usr/lib/lua/luci/view/web/apindex.htm
sed -i ':a;N;$!ba;s/>Wi-Fi密码：\n                                </><%:Wi-Fi密码：%>\n                                </g' /usr/lib/lua/luci/view/web/apindex.htm
sed -i 's/>连接设备数量 --</><%:连接设备数量 --%></g' /usr/lib/lua/luci/view/web/apindex.htm
sed -i 's/>设置</><%:设置%></g' /usr/lib/lua/luci/view/web/apindex.htm
sed -i 's/'\''Mesh组网设备'\''/'\''<%:Mesh组网设备%>'\''/g' /usr/lib/lua/luci/view/web/apindex.htm
sed -i 's/'\''Wi-Fi名称：'\''/'\''<%:Wi-Fi名称：%>'\''/g' /usr/lib/lua/luci/view/web/apindex.htm
sed -i 's/'\''Wi-Fi密码: 未设置'\''/'\''<%:Wi-Fi密码: 未设置%>'\''/g' /usr/lib/lua/luci/view/web/apindex.htm
sed -i 's/'\''连接设备数量：'\''/'\''<%:连接设备数量：%>'\''/g' /usr/lib/lua/luci/view/web/apindex.htm
sed -i 's/"Mesh组网"/"<%:Mesh组网%>"/g' /usr/lib/lua/luci/view/web/apindex.htm
# ======= FILE: /usr/lib/lua/luci/view/web/inc/g.js.htm ======= 
sed -i 's/>请靠近主路由</><%:请靠近主路由%></g' /usr/lib/lua/luci/view/web/inc/g.js.htm
sed -i 's/'\''此时5G网络已关闭'\''/'\''<%:此时5G网络已关闭%>'\''/g' /usr/lib/lua/luci/view/web/inc/g.js.htm
sed -i 's/'\''此时5G网络已打开'\''/'\''<%:此时5G网络已打开%>'\''/g' /usr/lib/lua/luci/view/web/inc/g.js.htm
sed -i 's/'\''请选择要添加的设备'\''/'\''<%:请选择要添加的设备%>'\''/g' /usr/lib/lua/luci/view/web/inc/g.js.htm
sed -i 's/'\''正在扩展Mesh节点(1-2分钟)\.\.\.'\''/'\''<%:正在扩展Mesh节点(1-2分钟)\.\.\.%>'\''/g' /usr/lib/lua/luci/view/web/inc/g.js.htm
sed -i 's/'\''正在同步Mesh节点配置\.\.\.'\''/'\''<%:正在同步Mesh节点配置\.\.\.%>'\''/g' /usr/lib/lua/luci/view/web/inc/g.js.htm
sed -i 's/'\''搜索并添加Mesh节点'\''/'\''<%:搜索并添加Mesh节点%>'\''/g' /usr/lib/lua/luci/view/web/inc/g.js.htm
sed -i 's/'\''没有搜索到可用的mesh节点'\''/'\''<%:没有搜索到可用的mesh节点%>'\''/g' /usr/lib/lua/luci/view/web/inc/g.js.htm
sed -i 's/"家"/"<%:家%>"/g' /usr/lib/lua/luci/view/web/inc/g.js.htm
sed -i 's/"客厅"/"<%:客厅%>"/g' /usr/lib/lua/luci/view/web/inc/g.js.htm
# ======= FILE: /usr/lib/lua/luci/view/web/inc/header.htm ======= 
sed -i ':a;N;$!ba;s/>\n            1\. 将要添加的Mesh节点路由放置主Mesh路由附近；</>\n            <%:1\. 将要添加的Mesh节点路由放置主Mesh路由附近；%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i ':a;N;$!ba;s/>\n            2\. 与主Mesh路由距离不超过3米；</>\n            <%:2\. 与主Mesh路由距离不超过3米；%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i ':a;N;$!ba;s/>\n            3\. 接通电源，等待路由器系统指示灯变为白\/蓝色；\n        </>\n            <%:3\. 接通电源，等待路由器系统指示灯变为白\/蓝色；%>\n        </g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/>开始搜索</><%:开始搜索%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i ':a;N;$!ba;s/>\n             为保证Mesh网络良好的使用体验，当前至多可支持10台Mesh路由器组网，更多Mesh路由器建议组成新的Mesh网络。\n              </>\n             <%:为保证Mesh网络良好的使用体验，当前至多可支持10台Mesh路由器组网，更多Mesh路由器建议组成新的Mesh网络。%>\n              </g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/>知道了</><%:知道了%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i ':a;N;$!ba;s/>\n             搜索并添加Mesh节点时，请先到Wi-Fi设置页面，开启5G Wi-Fi。\n              </>\n             <%:搜索并添加Mesh节点时，请先到Wi-Fi设置页面，开启5G Wi-Fi。%>\n              </g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/>去开启</><%:去开启%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/>搜索Mesh节点路由\.\.\.</><%:搜索Mesh节点路由\.\.\.%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/>取消</><%:取消%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/>添加</><%:添加%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/>重试</><%:重试%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i ':a;N;$!ba;s/>\n          未找到可用的Mesh节点，请确认：</>\n          <%:未找到可用的Mesh节点，请确认：%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i ':a;N;$!ba;s/>\n            1\.确认要添加的路由器支持Mesh功能；</>\n            <%:1\.确认要添加的路由器支持Mesh功能；%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i ':a;N;$!ba;s/>\n            2\.将要添加的Mesh节点路由升级至最新版本；</>\n            <%:2\.将要添加的Mesh节点路由升级至最新版本；%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i ':a;N;$!ba;s/>\n            3\.将要添加的Mesh节点路由靠近主Mesh路由器；</>\n            <%:3\.将要添加的Mesh节点路由靠近主Mesh路由器；%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i ':a;N;$!ba;s/>\n            4\.将要添加的Mesh节点路由上电；</>\n            <%:4\.将要添加的Mesh节点路由上电；%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i ':a;N;$!ba;s/>\n            5\.长按Reset按键恢复至出厂状态后重试\n          </>\n            <%:5\.长按Reset按键恢复至出厂状态后重试%>\n          </g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/>重新搜索</><%:重新搜索%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i ':a;N;$!ba;s/>\n             恭喜您，Wi-Fi覆盖增强！</>\n             <%:恭喜您，Wi-Fi覆盖增强！%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i ':a;N;$!ba;s/>\n            1\. 将新增Mesh节点路由放置在需要覆盖的地方。</>\n            <%:1\. 将新增Mesh节点路由放置在需要覆盖的地方。%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i ':a;N;$!ba;s/>\n            2\. 需等待一段时间后，新增路由会出现在管理列表中。</>\n            <%:2\. 需等待一段时间后，新增路由会出现在管理列表中。%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i ':a;N;$!ba;s/>\n            3\. 新增Mesh节点路由Wi-Fi信息与之前保持一致！\n        </>\n            <%:3\. 新增Mesh节点路由Wi-Fi信息与之前保持一致！%>\n        </g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/>客厅</><%:客厅%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/>主卧</><%:主卧%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/>次卧</><%:次卧%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/>书房</><%:书房%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/>厨房</><%:厨房%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/>办公室</><%:办公室%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/>地下室</><%:地下室%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/>卫生间</><%:卫生间%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/>阁楼</><%:阁楼%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/>阳台</><%:阳台%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/>餐厅</><%:餐厅%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/>确认</><%:确认%></g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/"客厅"/"<%:客厅%>"/g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/"主卧"/"<%:主卧%>"/g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/"次卧"/"<%:次卧%>"/g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/"书房"/"<%:书房%>"/g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/"厨房"/"<%:厨房%>"/g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/"办公室"/"<%:办公室%>"/g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/"地下室"/"<%:地下室%>"/g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/"卫生间"/"<%:卫生间%>"/g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/"阁楼"/"<%:阁楼%>"/g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/"阳台"/"<%:阳台%>"/g' /usr/lib/lua/luci/view/web/inc/header.htm
sed -i 's/"餐厅"/"<%:餐厅%>"/g' /usr/lib/lua/luci/view/web/inc/header.htm
# ======= FILE: /usr/lib/lua/luci/view/web/inc/sysinfo.htm ======= 
sed -i ':a;N;$!ba;s/>\n            当前系统时间：</>\n            <%:当前系统时间：%></g' /usr/lib/lua/luci/view/web/inc/sysinfo.htm
sed -i 's/>当前系统时间：</><%:当前系统时间：%></g' /usr/lib/lua/luci/view/web/inc/sysinfo.htm
sed -i 's/>当前系统时区：</><%:当前系统时区：%></g' /usr/lib/lua/luci/view/web/inc/sysinfo.htm
sed -i 's/>\*如需修改时区，请切换到主Mesh路由进行修改，会自动同步到子Mesh路由</><%:\*如需修改时区，请切换到主Mesh路由进行修改，会自动同步到子Mesh路由%></g' /usr/lib/lua/luci/view/web/inc/sysinfo.htm
