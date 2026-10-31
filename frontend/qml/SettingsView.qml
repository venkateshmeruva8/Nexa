import QtQuick 2.15
import QtQuick.Controls 2.15

Item {
    id: settingsRoot

    Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: mainCol.height + 60
        clip: true

        Column {
            id: mainCol
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(840, parent.width - 60)
            anchors.top: parent.top
            anchors.topMargin: 28
            spacing: 28

            // Section 1: Audio & Microphone
            Column {
                width: parent.width
                spacing: 14

                Row {
                    spacing: 8
                    Rectangle {
                        width: 3
                        height: 18
                        color: "#00b4ff"
                        radius: 1.5
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: "AUDIO & MICROPHONE"
                        font.pixelSize: 13
                        font.bold: true
                        font.family: "Segoe UI, Inter, sans-serif"
                        color: "#38bdf8"
                    }
                }

                // Microphone Control Card
                Rectangle {
                    width: parent.width
                    height: 80
                    radius: 12
                    color: "#081324"
                    border.color: "#132b4a"
                    border.width: 1.2

                    Row {
                        anchors.fill: parent
                        anchors.margins: 16
                        spacing: 16

                        Rectangle {
                            width: 44
                            height: 44
                            radius: 10
                            color: "#0c1d33"
                            border.color: "#1e3a5f"
                            border.width: 1
                            anchors.verticalCenter: parent.verticalCenter

                            Text {
                                text: "🎙️"
                                font.pixelSize: 20
                                anchors.centerIn: parent
                            }
                        }

                        Column {
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - 200
                            spacing: 4

                            Text {
                                text: "Input Microphone"
                                font.pixelSize: 13
                                font.bold: true
                                font.family: "Segoe UI, Inter, sans-serif"
                                color: "#f8fafc"
                            }

                            Text {
                                text: (controller && controller.micDeviceName) ? controller.micDeviceName : "Default System Microphone"
                                font.pixelSize: 11
                                font.family: "Segoe UI, Inter, sans-serif"
                                color: "#94a3b8"
                                elide: Text.ElideRight
                                width: parent.width
                            }
                        }

                        // Mute / Unmute Button
                        Rectangle {
                            width: 100
                            height: 36
                            radius: 8
                            anchors.verticalCenter: parent.verticalCenter
                            color: controller && controller.isMuted ? "#450a0a" : (muteMa.containsMouse ? "#1e293b" : "#0f172a")
                            border.color: controller && controller.isMuted ? "#ef4444" : "#334155"
                            border.width: 1

                            Text {
                                text: controller && controller.isMuted ? "Unmute Mic" : "Mute Mic"
                                font.pixelSize: 12
                                font.family: "Segoe UI, Inter, sans-serif"
                                color: controller && controller.isMuted ? "#f87171" : "#f1f5f9"
                                anchors.centerIn: parent
                            }

                            MouseArea {
                                id: muteMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (controller) controller.toggleMute()
                                }
                            }
                        }
                    }
                }

                // Master Output Volume Card
                Rectangle {
                    width: parent.width
                    height: 80
                    radius: 12
                    color: "#081324"
                    border.color: "#132b4a"
                    border.width: 1.2

                    Row {
                        anchors.fill: parent
                        anchors.margins: 16
                        spacing: 16

                        Rectangle {
                            width: 44
                            height: 44
                            radius: 10
                            color: "#0c1d33"
                            border.color: "#1e3a5f"
                            border.width: 1
                            anchors.verticalCenter: parent.verticalCenter

                            Text {
                                text: "🔊"
                                font.pixelSize: 20
                                anchors.centerIn: parent
                            }
                        }

                        Column {
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - 240
                            spacing: 4

                            Text {
                                text: "Master Output Volume"
                                font.pixelSize: 13
                                font.bold: true
                                font.family: "Segoe UI, Inter, sans-serif"
                                color: "#f8fafc"
                            }

                            Text {
                                text: "Level: " + (controller ? controller.volumeLevel : 60) + "%"
                                font.pixelSize: 11
                                font.family: "Segoe UI, Inter, sans-serif"
                                color: "#00b4ff"
                            }
                        }

                        // Volume Down Button
                        Rectangle {
                            width: 40
                            height: 36
                            radius: 8
                            anchors.verticalCenter: parent.verticalCenter
                            color: vdownMa.containsMouse ? "#1e293b" : "#0f172a"
                            border.color: "#334155"
                            border.width: 1

                            Text {
                                text: "-5%"
                                font.pixelSize: 11
                                font.family: "Segoe UI, Inter, sans-serif"
                                color: "#f1f5f9"
                                anchors.centerIn: parent
                            }

                            MouseArea {
                                id: vdownMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (controller) {
                                        var cur = controller.volumeLevel
                                        controller.setVolume(Math.max(0, cur - 5))
                                    }
                                }
                            }
                        }

                        // Volume Up Button
                        Rectangle {
                            width: 40
                            height: 36
                            radius: 8
                            anchors.verticalCenter: parent.verticalCenter
                            color: vupMa.containsMouse ? "#1e293b" : "#0f172a"
                            border.color: "#334155"
                            border.width: 1

                            Text {
                                text: "+5%"
                                font.pixelSize: 11
                                font.family: "Segoe UI, Inter, sans-serif"
                                color: "#f1f5f9"
                                anchors.centerIn: parent
                            }

                            MouseArea {
                                id: vupMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (controller) {
                                        var cur = controller.volumeLevel
                                        controller.setVolume(Math.min(100, cur + 5))
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // Section 2: Assistant Behavior & LiveKit
            Column {
                width: parent.width
                spacing: 14

                Row {
                    spacing: 8
                    Rectangle {
                        width: 3
                        height: 18
                        color: "#10b981"
                        radius: 1.5
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: "ASSISTANT BEHAVIOR"
                        font.pixelSize: 13
                        font.bold: true
                        font.family: "Segoe UI, Inter, sans-serif"
                        color: "#34d399"
                    }
                }

                // Voice Listening Toggle Card
                Rectangle {
                    width: parent.width
                    height: 80
                    radius: 12
                    color: "#081324"
                    border.color: "#132b4a"
                    border.width: 1.2

                    Row {
                        anchors.fill: parent
                        anchors.margins: 16
                        spacing: 16

                        Rectangle {
                            width: 44
                            height: 44
                            radius: 10
                            color: "#0c1d33"
                            border.color: "#1e3a5f"
                            border.width: 1
                            anchors.verticalCenter: parent.verticalCenter

                            Text {
                                text: "🧠"
                                font.pixelSize: 20
                                anchors.centerIn: parent
                            }
                        }

                        Column {
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - 200
                            spacing: 4

                            Text {
                                text: "Continuous Voice Listening"
                                font.pixelSize: 13
                                font.bold: true
                                font.family: "Segoe UI, Inter, sans-serif"
                                color: "#f8fafc"
                            }

                            Text {
                                text: "Status: " + (controller ? controller.stateText : "Ready")
                                font.pixelSize: 11
                                font.family: "Segoe UI, Inter, sans-serif"
                                color: "#94a3b8"
                            }
                        }

                        // Toggle Listening Button
                        Rectangle {
                            width: 100
                            height: 36
                            radius: 8
                            anchors.verticalCenter: parent.verticalCenter
                            color: controller && controller.isListening ? "#064e3b" : (listenMa.containsMouse ? "#1e293b" : "#0f172a")
                            border.color: controller && controller.isListening ? "#10b981" : "#334155"
                            border.width: 1

                            Text {
                                text: controller && controller.isListening ? "Listening" : "Paused"
                                font.pixelSize: 12
                                font.family: "Segoe UI, Inter, sans-serif"
                                color: controller && controller.isListening ? "#34d399" : "#94a3b8"
                                anchors.centerIn: parent
                            }

                            MouseArea {
                                id: listenMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (controller) controller.toggleListening()
                                }
                            }
                        }
                    }
                }

                // Cloud Status Card
                Rectangle {
                    width: parent.width
                    height: 64
                    radius: 12
                    color: "#081324"
                    border.color: "#132b4a"
                    border.width: 1.2

                    Row {
                        anchors.fill: parent
                        anchors.margins: 16
                        spacing: 16

                        Text {
                            text: "LiveKit Cloud Session:"
                            font.pixelSize: 13
                            font.bold: true
                            font.family: "Segoe UI, Inter, sans-serif"
                            color: "#f8fafc"
                            anchors.verticalCenter: parent.verticalCenter
                        }

                        Item {
                            width: Math.max(10, parent.width - 280)
                            height: 1
                        }

                        Rectangle {
                            height: 26
                            width: 140
                            radius: 13
                            color: "#0a2540"
                            border.color: "#00b4ff"
                            border.width: 1
                            anchors.verticalCenter: parent.verticalCenter

                            Text {
                                text: controller ? controller.connectionStatus : "Disconnected"
                                font.pixelSize: 11
                                font.bold: true
                                font.family: "Segoe UI, Inter, sans-serif"
                                color: "#38bdf8"
                                anchors.centerIn: parent
                            }
                        }
                    }
                }
            }

            // Section 3: System Telemetry & Maintenance
            Column {
                width: parent.width
                spacing: 14

                Row {
                    spacing: 8
                    Rectangle {
                        width: 3
                        height: 18
                        color: "#f59e0b"
                        radius: 1.5
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: "SYSTEM TELEMETRY & MAINTENANCE"
                        font.pixelSize: 13
                        font.bold: true
                        font.family: "Segoe UI, Inter, sans-serif"
                        color: "#fbbf24"
                    }
                }

                Grid {
                    width: parent.width
                    columns: 2
                    spacing: 14

                    // Battery Tile
                    Rectangle {
                        width: (mainCol.width - 14) / 2
                        height: 64
                        radius: 12
                        color: "#081324"
                        border.color: "#132b4a"
                        border.width: 1

                        Row {
                            anchors.centerIn: parent
                            spacing: 10
                            Text { text: "🔋"; font.pixelSize: 18 }
                            Text {
                                text: "Battery: " + (controller ? controller.batteryLevel : 100) + "%" + ((controller && controller.batteryCharging) ? " (Charging)" : "")
                                font.pixelSize: 12
                                font.family: "Segoe UI, Inter, sans-serif"
                                color: "#f8fafc"
                            }
                        }
                    }

                    // Network Tile
                    Rectangle {
                        width: (mainCol.width - 14) / 2
                        height: 64
                        radius: 12
                        color: "#081324"
                        border.color: "#132b4a"
                        border.width: 1

                        Row {
                            anchors.centerIn: parent
                            spacing: 10
                            Text { text: "📶"; font.pixelSize: 18 }
                            Text {
                                text: "Network: " + (controller ? controller.networkStatus : "Connected")
                                font.pixelSize: 12
                                font.family: "Segoe UI, Inter, sans-serif"
                                color: "#f8fafc"
                            }
                        }
                    }

                    // Refresh Telemetry Button
                    Rectangle {
                        width: (mainCol.width - 14) / 2
                        height: 48
                        radius: 10
                        color: refMa.containsMouse ? "#1e293b" : "#0f172a"
                        border.color: "#334155"
                        border.width: 1

                        Row {
                            anchors.centerIn: parent
                            spacing: 8
                            Text { text: "🔄"; font.pixelSize: 14 }
                            Text {
                                text: "Refresh Telemetry"
                                font.pixelSize: 12
                                font.family: "Segoe UI, Inter, sans-serif"
                                color: "#f1f5f9"
                            }
                        }

                        MouseArea {
                            id: refMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (controller) controller.refreshTelemetry()
                            }
                        }
                    }

                    // Clear Messages Button
                    Rectangle {
                        width: (mainCol.width - 14) / 2
                        height: 48
                        radius: 10
                        color: clrMa.containsMouse ? "#2a1515" : "#191015"
                        border.color: "#451a1a"
                        border.width: 1

                        Row {
                            anchors.centerIn: parent
                            spacing: 8
                            Text { text: "🗑️"; font.pixelSize: 14 }
                            Text {
                                text: "Clear Chat History"
                                font.pixelSize: 12
                                font.family: "Segoe UI, Inter, sans-serif"
                                color: "#fca5a5"
                            }
                        }

                        MouseArea {
                            id: clrMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (controller) controller.clearMessages()
                            }
                        }
                    }
                }
            }
        }
    }
}
