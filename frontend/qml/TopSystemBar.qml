import QtQuick 2.15
import QtQuick.Controls 2.15

Item {
    id: root
    height: 60
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.top: parent.top

    // Brand Logo on the Left
    Row {
        id: brandRow
        anchors.left: parent.left
        anchors.leftMargin: 84
        anchors.verticalCenter: parent.verticalCenter
        spacing: 14

        Text {
            text: "N"
            font.pixelSize: 22
            font.weight: Font.DemiBold
            font.family: "Segoe UI, Inter, sans-serif"
            color: "#ffffff"
        }
        Text {
            text: "E"
            font.pixelSize: 22
            font.weight: Font.DemiBold
            font.family: "Segoe UI, Inter, sans-serif"
            color: "#ffffff"
        }
        Text {
            text: "X"
            font.pixelSize: 22
            font.weight: Font.DemiBold
            font.family: "Segoe UI, Inter, sans-serif"
            color: "#ffffff"
        }
        // Stylized 'A' with cyan inner delta
        Item {
            width: 22
            height: 24
            Canvas {
                id: aCanvas
                anchors.fill: parent
                onPaint: {
                    var ctx = getContext("2d");
                    ctx.clearRect(0, 0, width, height);

                    // Outer chevron legs of 'A'
                    ctx.strokeStyle = "#ffffff";
                    ctx.lineWidth = 2.6;
                    ctx.lineCap = "round";
                    ctx.lineJoin = "miter";
                    ctx.beginPath();
                    ctx.moveTo(3, height - 2);
                    ctx.lineTo(width / 2, 2);
                    ctx.lineTo(width - 3, height - 2);
                    ctx.stroke();

                    // Glowing cyan drop / delta inside apex
                    ctx.fillStyle = "#0088ff";
                    ctx.beginPath();
                    ctx.moveTo(width / 2, 9);
                    ctx.lineTo(width / 2 - 3.5, 17);
                    ctx.lineTo(width / 2 + 3.5, 17);
                    ctx.closePath();
                    ctx.fill();
                }
            }
        }
    }

    // Right System Bar items
    Row {
        id: sysTray
        anchors.right: parent.right
        anchors.rightMargin: 24
        anchors.verticalCenter: parent.verticalCenter
        spacing: 16

        // 1. Battery Item
        Row {
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8
            // Battery icon
            Item {
                width: 24
                height: 14
                anchors.verticalCenter: parent.verticalCenter

                Rectangle {
                    width: 20
                    height: 13
                    radius: 2.5
                    color: "transparent"
                    border.color: "#38bdf8"
                    border.width: 1.5

                    // Fill level
                    Rectangle {
                        anchors.left: parent.left
                        anchors.leftMargin: 2
                        anchors.verticalCenter: parent.verticalCenter
                        height: 9
                        width: Math.max(2, (parent.width - 4) * Math.min(1.0, controller.batteryLevel / 100.0))
                        radius: 1.5
                        color: "#38bdf8"
                    }
                }
                // Terminal bump
                Rectangle {
                    x: 20
                    y: 4
                    width: 2.5
                    height: 5
                    radius: 1
                    color: "#38bdf8"
                }
            }

            Text {
                text: controller.batteryLevel + "%"
                font.pixelSize: 13
                font.family: "Segoe UI, Inter, sans-serif"
                color: "#e2e8f0"
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        // Divider
        Rectangle {
            width: 1
            height: 14
            color: "#1e293b"
            anchors.verticalCenter: parent.verticalCenter
        }

        // 2. Wi-Fi Item
        Row {
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8

            // Wi-Fi icon canvas
            Canvas {
                width: 16
                height: 14
                anchors.verticalCenter: parent.verticalCenter
                onPaint: {
                    var ctx = getContext("2d");
                    ctx.clearRect(0, 0, width, height);
                    ctx.strokeStyle = "#38bdf8";
                    ctx.lineWidth = 1.4;
                    ctx.lineCap = "round";

                    // Outer arc
                    ctx.beginPath();
                    ctx.arc(8, 12, 10, -Math.PI * 0.75, -Math.PI * 0.25);
                    ctx.stroke();

                    // Middle arc
                    ctx.beginPath();
                    ctx.arc(8, 12, 6.5, -Math.PI * 0.75, -Math.PI * 0.25);
                    ctx.stroke();

                    // Dot
                    ctx.fillStyle = "#38bdf8";
                    ctx.beginPath();
                    ctx.arc(8, 11.5, 1.5, 0, 2 * Math.PI);
                    ctx.fill();
                }
            }

            Text {
                text: controller.networkStatus
                font.pixelSize: 13
                font.family: "Segoe UI, Inter, sans-serif"
                color: "#e2e8f0"
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        // Divider
        Rectangle {
            width: 1
            height: 14
            color: "#1e293b"
            anchors.verticalCenter: parent.verticalCenter
        }

        // 3. Volume Item
        Row {
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8

            // Speaker icon canvas
            Canvas {
                width: 16
                height: 14
                anchors.verticalCenter: parent.verticalCenter
                onPaint: {
                    var ctx = getContext("2d");
                    ctx.clearRect(0, 0, width, height);
                    ctx.fillStyle = "#38bdf8";
                    ctx.strokeStyle = "#38bdf8";
                    ctx.lineWidth = 1.3;
                    ctx.lineCap = "round";

                    // Speaker cone
                    ctx.beginPath();
                    ctx.moveTo(2, 4.5);
                    ctx.lineTo(5, 4.5);
                    ctx.lineTo(8.5, 1.5);
                    ctx.lineTo(8.5, 12.5);
                    ctx.lineTo(5, 9.5);
                    ctx.lineTo(2, 9.5);
                    ctx.closePath();
                    ctx.fill();

                    // Sound wave
                    ctx.beginPath();
                    ctx.arc(8.5, 7, 4.5, -Math.PI * 0.35, Math.PI * 0.35);
                    ctx.stroke();
                }
            }

            Text {
                text: controller.volumeLevel + "%"
                font.pixelSize: 13
                font.family: "Segoe UI, Inter, sans-serif"
                color: "#e2e8f0"
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        // Divider
        Rectangle {
            width: 1
            height: 14
            color: "#1e293b"
            anchors.verticalCenter: parent.verticalCenter
        }

        // 4. Date & Time Item
        Text {
            text: controller.dateTimeString
            font.pixelSize: 13
            font.family: "Segoe UI, Inter, sans-serif"
            color: "#f8fafc"
            anchors.verticalCenter: parent.verticalCenter
        }

        // Divider
        Rectangle {
            width: 1
            height: 14
            color: "#1e293b"
            anchors.verticalCenter: parent.verticalCenter
        }

        // 5. Window Controls (Minimize, Maximize, Close)
        Row {
            anchors.verticalCenter: parent.verticalCenter
            spacing: 6

            // Minimize button
            Rectangle {
                width: 28
                height: 28
                radius: 4
                color: minMa.containsMouse ? "#1e293b" : "transparent"
                anchors.verticalCenter: parent.verticalCenter

                Rectangle {
                    width: 12
                    height: 1.5
                    color: "#cbd5e1"
                    anchors.centerIn: parent
                }
                MouseArea {
                    id: minMa
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: controller.minimizeWindow(appWindow)
                }
            }

            // Maximize button
            Rectangle {
                width: 28
                height: 28
                radius: 4
                color: maxMa.containsMouse ? "#1e293b" : "transparent"
                anchors.verticalCenter: parent.verticalCenter

                Rectangle {
                    width: 11
                    height: 11
                    radius: 2
                    color: "transparent"
                    border.color: "#cbd5e1"
                    border.width: 1.5
                    anchors.centerIn: parent
                }
                MouseArea {
                    id: maxMa
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: controller.maximizeRestoreWindow(appWindow)
                }
            }

            // Close button
            Rectangle {
                width: 28
                height: 28
                radius: 4
                color: closeMa.containsMouse ? "#ef4444" : "transparent"
                anchors.verticalCenter: parent.verticalCenter

                Canvas {
                    width: 12
                    height: 12
                    anchors.centerIn: parent
                    onPaint: {
                        var ctx = getContext("2d");
                        ctx.clearRect(0, 0, width, height);
                        ctx.strokeStyle = closeMa.containsMouse ? "#ffffff" : "#cbd5e1";
                        ctx.lineWidth = 1.5;
                        ctx.lineCap = "round";

                        ctx.beginPath();
                        ctx.moveTo(1, 1);
                        ctx.lineTo(width - 1, height - 1);
                        ctx.moveTo(width - 1, 1);
                        ctx.lineTo(1, height - 1);
                        ctx.stroke();
                    }
                }
                MouseArea {
                    id: closeMa
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: controller.closeWindow(appWindow)
                }
            }
        }
    }
}
