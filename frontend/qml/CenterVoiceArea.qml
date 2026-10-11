import QtQuick 2.15
import QtQuick.Controls 2.15

Item {
    id: root

    // 1. NEXA Brand Text below the orb
    Row {
        id: titleRow
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: Math.min(575, Math.max(380, parent.height - 350))
        spacing: 16

        Text {
            text: "N"
            font.pixelSize: 26
            font.weight: Font.DemiBold
            font.family: "Segoe UI, Inter, sans-serif"
            color: "#ffffff"
        }
        Text {
            text: "E"
            font.pixelSize: 26
            font.weight: Font.DemiBold
            font.family: "Segoe UI, Inter, sans-serif"
            color: "#ffffff"
        }
        Text {
            text: "X"
            font.pixelSize: 26
            font.weight: Font.DemiBold
            font.family: "Segoe UI, Inter, sans-serif"
            color: "#ffffff"
        }
        // Stylized 'A'
        Item {
            width: 26
            height: 28
            Canvas {
                anchors.fill: parent
                onPaint: {
                    var ctx = getContext("2d");
                    ctx.clearRect(0, 0, width, height);

                    ctx.strokeStyle = "#ffffff";
                    ctx.lineWidth = 3.0;
                    ctx.lineCap = "round";
                    ctx.beginPath();
                    ctx.moveTo(3, height - 2);
                    ctx.lineTo(width / 2, 2);
                    ctx.lineTo(width - 3, height - 2);
                    ctx.stroke();

                    ctx.fillStyle = "#0088ff";
                    ctx.beginPath();
                    ctx.moveTo(width / 2, 10);
                    ctx.lineTo(width / 2 - 4.5, 19);
                    ctx.lineTo(width / 2 + 4.5, 19);
                    ctx.closePath();
                    ctx.fill();
                }
            }
        }
    }

    // 2. Listening Status Text
    Text {
        id: statusLabel
        text: controller.stateText
        font.pixelSize: 18
        font.family: "Segoe UI, Inter, sans-serif"
        color: "#e2e8f0"
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: titleRow.bottom
        anchors.topMargin: 12
    }

    // 3. Audio Waveform
    Item {
        id: waveformContainer
        width: 360
        height: 60
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: statusLabel.bottom
        anchors.topMargin: 20

        // Subtle horizontal blue baseline glow
        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left
            anchors.right: parent.right
            height: 1.5
            color: "#0088ff"
            opacity: 0.35
        }

        Row {
            anchors.centerIn: parent
            spacing: 4

            Repeater {
                model: controller.waveformAmplitudes
                Rectangle {
                    width: 3
                    height: Math.max(3, modelData * 54)
                    radius: 1.5
                    anchors.verticalCenter: parent.verticalCenter
                    color: modelData > 0.7 ? "#ffffff" : "#2cb5ff"

                    // Smooth animation
                    Behavior on height {
                        NumberAnimation { duration: 35; easing.type: Easing.OutQuad }
                    }
                }
            }
        }
    }

    // 4. Control Dock (Pill with Mute, Main Mic, and Stop)
    Item {
        id: dockContainer
        width: 370
        height: 114
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Math.min(68, Math.max(24, Math.round(parent.height * 0.05)))

        // Pill background
        Rectangle {
            width: parent.width
            height: 84
            radius: 42
            anchors.centerIn: parent
            color: "#0a1322"
            opacity: 0.85
            border.color: "#18263a"
            border.width: 1.2
        }

        // Left: Mute Button
        Rectangle {
            id: muteBtn
            width: 58
            height: 58
            radius: 29
            anchors.left: parent.left
            anchors.leftMargin: 18
            anchors.verticalCenter: parent.verticalCenter
            color: controller.isMuted ? "#2a1515" : (muteMa.containsMouse ? "#1c2b42" : "#111c2e")
            border.color: controller.isMuted ? "#ef4444" : "#1d2c44"
            border.width: 1.0

            Canvas {
                width: 26
                height: 26
                anchors.centerIn: parent
                onPaint: {
                    var ctx = getContext("2d");
                    ctx.clearRect(0, 0, width, height);
                    ctx.strokeStyle = controller.isMuted ? "#ef4444" : "#cbd5e1";
                    ctx.lineWidth = 1.8;
                    ctx.lineCap = "round";

                    // Mic capsule outline
                    ctx.beginPath();
                    ctx.arc(13, 9, 4, Math.PI, 0, false);
                    ctx.lineTo(17, 14);
                    ctx.arc(13, 14, 4, 0, Math.PI, false);
                    ctx.closePath();
                    ctx.stroke();

                    // Stand & base
                    ctx.beginPath();
                    ctx.moveTo(13, 18);
                    ctx.lineTo(13, 22);
                    ctx.moveTo(9, 22);
                    ctx.lineTo(17, 22);
                    ctx.stroke();

                    // Diagonal slash across
                    ctx.strokeStyle = "#ffffff";
                    ctx.lineWidth = 2.0;
                    ctx.beginPath();
                    ctx.moveTo(5, 5);
                    ctx.lineTo(21, 21);
                    ctx.stroke();
                }
            }

            MouseArea {
                id: muteMa
                anchors.fill: parent
                hoverEnabled: true
                onClicked: controller.toggleMute()
            }
        }

        // Center: Glowing Neon Main Mic Button
        Item {
            id: mainMicBtn
            width: 114
            height: 114
            anchors.centerIn: parent

            // Outer Neon Halo Ring
            Rectangle {
                anchors.fill: parent
                radius: width / 2
                color: "transparent"
                border.color: controller.isListening ? "#0088ff" : "#334155"
                border.width: 4.5

                // Inner deep cobalt circle
                Rectangle {
                    anchors.centerIn: parent
                    width: parent.width - 9
                    height: parent.height - 9
                    radius: width / 2
                    color: controller.isListening ? "#051124" : "#0d1829"
                }
            }

            // Microphone Icon
            Canvas {
                width: 32
                height: 32
                anchors.centerIn: parent
                onPaint: {
                    var ctx = getContext("2d");
                    ctx.clearRect(0, 0, width, height);
                    ctx.fillStyle = "#ffffff";
                    ctx.strokeStyle = "#ffffff";
                    ctx.lineWidth = 2.2;
                    ctx.lineCap = "round";

                    // Mic body
                    ctx.beginPath();
                    ctx.arc(16, 10, 5, Math.PI, 0, false);
                    ctx.lineTo(21, 16);
                    ctx.arc(16, 16, 5, 0, Math.PI, false);
                    ctx.closePath();
                    ctx.fill();

                    // Cradle
                    ctx.beginPath();
                    ctx.arc(16, 15, 8.5, 0, Math.PI, false);
                    ctx.stroke();

                    // Stem & foot
                    ctx.beginPath();
                    ctx.moveTo(16, 23.5);
                    ctx.lineTo(16, 28);
                    ctx.moveTo(11, 28);
                    ctx.lineTo(21, 28);
                    ctx.stroke();
                }
            }

            MouseArea {
                id: micMa
                anchors.fill: parent
                hoverEnabled: true
                onClicked: controller.toggleListening()
            }
        }

        // Right: Stop Button
        Rectangle {
            id: stopBtn
            width: 58
            height: 58
            radius: 29
            anchors.right: parent.right
            anchors.rightMargin: 18
            anchors.verticalCenter: parent.verticalCenter
            color: stopMa.containsMouse ? "#1c2b42" : "#111c2e"
            border.color: "#1d2c44"
            border.width: 1.0

            // White rounded square stop icon
            Rectangle {
                width: 18
                height: 18
                radius: 4
                color: "#ffffff"
                anchors.centerIn: parent
            }

            MouseArea {
                id: stopMa
                anchors.fill: parent
                hoverEnabled: true
                onClicked: controller.stopListening()
            }
        }
    }
}
