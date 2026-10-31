import QtQuick 2.15
import QtQuick.Controls 2.15

Item {
    id: root
    width: 64
    anchors.left: parent.left
    anchors.top: parent.top
    anchors.bottom: parent.bottom

    // Right border separator
    Rectangle {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 1
        color: "#0a192f"
    }

    Connections {
        target: controller
        function onNavChanged() {
            homeCanvas.requestPaint()
            chatCanvas.requestPaint()
            gridCanvas.requestPaint()
            setCanvas.requestPaint()
        }
    }

    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: 96
        spacing: 28

        // 1. Home Button
        Rectangle {
            width: 48
            height: 48
            radius: 12
            color: controller.activeNav === 0 ? "#0a2540" : (homeMa.containsMouse ? "#0f172a" : "transparent")
            border.color: controller.activeNav === 0 ? "#0077ff" : "transparent"
            border.width: controller.activeNav === 0 ? 1.8 : 0

            // Left neon indicator pill
            Rectangle {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                width: 3.5
                height: controller.activeNav === 0 ? 24 : 0
                radius: 1.75
                color: "#00b4ff"
                Behavior on height { NumberAnimation { duration: 160 } }
            }

            Canvas {
                id: homeCanvas
                width: 22
                height: 22
                anchors.centerIn: parent
                onPaint: {
                    var ctx = getContext("2d");
                    ctx.clearRect(0, 0, width, height);
                    ctx.strokeStyle = controller.activeNav === 0 ? "#00b4ff" : (homeMa.containsMouse ? "#ffffff" : "#e2e8f0");
                    ctx.lineWidth = 1.8;
                    ctx.lineCap = "round";
                    ctx.lineJoin = "round";

                    // Roof
                    ctx.beginPath();
                    ctx.moveTo(3, 9.5);
                    ctx.lineTo(11, 3);
                    ctx.lineTo(19, 9.5);
                    ctx.stroke();

                    // House walls & door
                    ctx.beginPath();
                    ctx.moveTo(5, 8.5);
                    ctx.lineTo(5, 19);
                    ctx.lineTo(17, 19);
                    ctx.lineTo(17, 8.5);
                    // Door
                    ctx.moveTo(9, 19);
                    ctx.lineTo(9, 13);
                    ctx.lineTo(13, 13);
                    ctx.lineTo(13, 19);
                    ctx.stroke();
                }
            }

            MouseArea {
                id: homeMa
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    controller.selectNav(0)
                    homeCanvas.requestPaint()
                }
            }
        }

        // 2. Chat Bubble Button
        Rectangle {
            width: 48
            height: 48
            radius: 12
            color: controller.activeNav === 1 ? "#0a2540" : (chatMa.containsMouse ? "#0f172a" : "transparent")
            border.color: controller.activeNav === 1 ? "#0077ff" : "transparent"
            border.width: controller.activeNav === 1 ? 1.8 : 0

            // Left neon indicator pill
            Rectangle {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                width: 3.5
                height: controller.activeNav === 1 ? 24 : 0
                radius: 1.75
                color: "#00b4ff"
                Behavior on height { NumberAnimation { duration: 160 } }
            }

            Canvas {
                id: chatCanvas
                width: 22
                height: 22
                anchors.centerIn: parent
                onPaint: {
                    var ctx = getContext("2d");
                    ctx.clearRect(0, 0, width, height);
                    ctx.strokeStyle = controller.activeNav === 1 ? "#00b4ff" : (chatMa.containsMouse ? "#ffffff" : "#e2e8f0");
                    ctx.lineWidth = 1.8;
                    ctx.lineCap = "round";
                    ctx.lineJoin = "round";

                    // Chat bubble rectangle with bottom tail
                    ctx.beginPath();
                    ctx.moveTo(4, 4);
                    ctx.lineTo(18, 4);
                    ctx.lineTo(18, 15);
                    ctx.lineTo(9, 15);
                    ctx.lineTo(6, 18.5);
                    ctx.lineTo(6, 15);
                    ctx.lineTo(4, 15);
                    ctx.closePath();
                    ctx.stroke();

                    // Inner dash
                    ctx.beginPath();
                    ctx.moveTo(8.5, 9.5);
                    ctx.lineTo(13.5, 9.5);
                    ctx.stroke();
                }
            }

            MouseArea {
                id: chatMa
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    controller.selectNav(1)
                    chatCanvas.requestPaint()
                }
            }
        }

        // 3. Grid / Dashboard Apps Button
        Rectangle {
            width: 48
            height: 48
            radius: 12
            color: controller.activeNav === 2 ? "#0a2540" : (gridMa.containsMouse ? "#0f172a" : "transparent")
            border.color: controller.activeNav === 2 ? "#0077ff" : "transparent"
            border.width: controller.activeNav === 2 ? 1.8 : 0

            // Left neon indicator pill
            Rectangle {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                width: 3.5
                height: controller.activeNav === 2 ? 24 : 0
                radius: 1.75
                color: "#00b4ff"
                Behavior on height { NumberAnimation { duration: 160 } }
            }

            Canvas {
                id: gridCanvas
                width: 22
                height: 22
                anchors.centerIn: parent
                onPaint: {
                    var ctx = getContext("2d");
                    ctx.clearRect(0, 0, width, height);
                    ctx.strokeStyle = controller.activeNav === 2 ? "#00b4ff" : (gridMa.containsMouse ? "#ffffff" : "#e2e8f0");
                    ctx.lineWidth = 1.8;
                    ctx.lineCap = "round";

                    // 4 small rounded squares
                    var sz = 6;
                    var gap = 4;
                    var x0 = 3, y0 = 3;
                    var x1 = x0 + sz + gap, y1 = y0 + sz + gap;

                    ctx.strokeRect(x0, y0, sz, sz);
                    ctx.strokeRect(x1, y0, sz, sz);
                    ctx.strokeRect(x0, y1, sz, sz);
                    ctx.strokeRect(x1, y1, sz, sz);
                }
            }

            MouseArea {
                id: gridMa
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    controller.selectNav(2)
                    gridCanvas.requestPaint()
                }
            }
        }

        // 4. Settings Button
        Rectangle {
            width: 48
            height: 48
            radius: 12
            color: controller.activeNav === 3 ? "#0a2540" : (setMa.containsMouse ? "#0f172a" : "transparent")
            border.color: controller.activeNav === 3 ? "#0077ff" : "transparent"
            border.width: controller.activeNav === 3 ? 1.8 : 0

            // Left neon indicator pill
            Rectangle {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                width: 3.5
                height: controller.activeNav === 3 ? 24 : 0
                radius: 1.75
                color: "#00b4ff"
                Behavior on height { NumberAnimation { duration: 160 } }
            }

            Canvas {
                id: setCanvas
                width: 22
                height: 22
                anchors.centerIn: parent
                onPaint: {
                    var ctx = getContext("2d");
                    ctx.clearRect(0, 0, width, height);
                    ctx.strokeStyle = controller.activeNav === 3 ? "#00b4ff" : (setMa.containsMouse ? "#ffffff" : "#e2e8f0");
                    ctx.lineWidth = 1.8;
                    ctx.lineCap = "round";

                    // Gear circle
                    ctx.beginPath();
                    ctx.arc(11, 11, 4.5, 0, 2 * Math.PI);
                    ctx.stroke();

                    // Gear teeth (8 teeth)
                    for (var a = 0; a < 8; a++) {
                        var angle = a * Math.PI / 4;
                        var x1 = 11 + Math.cos(angle) * 6;
                        var y1 = 11 + Math.sin(angle) * 6;
                        var x2 = 11 + Math.cos(angle) * 8.5;
                        var y2 = 11 + Math.sin(angle) * 8.5;
                        ctx.beginPath();
                        ctx.moveTo(x1, y1);
                        ctx.lineTo(x2, y2);
                        ctx.stroke();
                    }
                }
            }

            MouseArea {
                id: setMa
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    controller.selectNav(3)
                    setCanvas.requestPaint()
                }
            }
        }
    }
}
