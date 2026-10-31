import QtQuick 2.15
import QtQuick.Controls 2.15

Item {
    id: appsRoot

    Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: mainCol.height + 60
        clip: true

        Column {
            id: mainCol
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(920, parent.width - 60)
            anchors.top: parent.top
            anchors.topMargin: 28
            spacing: 28

            // Section 1: Desktop Applications
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
                        text: "DESKTOP APPLICATIONS"
                        font.pixelSize: 13
                        font.bold: true
                        font.family: "Segoe UI, Inter, sans-serif"
                        color: "#38bdf8"
                    }
                }

                Grid {
                    width: parent.width
                    columns: parent.width > 700 ? 4 : (parent.width > 480 ? 2 : 1)
                    spacing: 14

                    Repeater {
                        model: [
                            { name: "Google Chrome", app: "chrome", desc: "Web browser", icon: "🌐" },
                            { name: "Notepad", app: "notepad", desc: "Text editor", icon: "📝" },
                            { name: "Calculator", app: "calc", desc: "Calculations", icon: "🔢" },
                            { name: "File Explorer", app: "explorer", desc: "System files", icon: "📁" },
                            { name: "Terminal", app: "cmd", desc: "Command prompt", icon: "💻" },
                            { name: "VS Code", app: "code", desc: "Code editor", icon: "⚡" },
                            { name: "Task Manager", app: "taskmgr", desc: "Processes", icon: "📊" },
                            { name: "Spotify", app: "spotify", desc: "Music player", icon: "🎵" }
                        ]

                        Rectangle {
                            width: (mainCol.width - (parent.columns - 1) * 14) / parent.columns
                            height: 90
                            radius: 12
                            color: appMa.containsMouse ? "#0f2038" : "#081324"
                            opacity: 0.90
                            border.color: appMa.containsMouse ? "#00b4ff" : "#132b4a"
                            border.width: 1.2

                            Behavior on border.color { ColorAnimation { duration: 150 } }
                            Behavior on color { ColorAnimation { duration: 150 } }

                            Row {
                                anchors.fill: parent
                                anchors.margins: 12
                                spacing: 12

                                Rectangle {
                                    width: 44
                                    height: 44
                                    radius: 10
                                    color: "#0c1d33"
                                    border.color: "#1e3a5f"
                                    border.width: 1
                                    anchors.verticalCenter: parent.verticalCenter

                                    Text {
                                        text: modelData.icon
                                        font.pixelSize: 20
                                        anchors.centerIn: parent
                                    }
                                }

                                Column {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: parent.width - 56
                                    spacing: 4

                                    Text {
                                        text: modelData.name
                                        font.pixelSize: 13
                                        font.bold: true
                                        font.family: "Segoe UI, Inter, sans-serif"
                                        color: "#f8fafc"
                                        elide: Text.ElideRight
                                        width: parent.width
                                    }

                                    Text {
                                        text: modelData.desc
                                        font.pixelSize: 11
                                        font.family: "Segoe UI, Inter, sans-serif"
                                        color: "#94a3b8"
                                        elide: Text.ElideRight
                                        width: parent.width
                                    }
                                }
                            }

                            MouseArea {
                                id: appMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (controller) {
                                        controller.launchApp(modelData.app)
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // Section 2: NEXA Quick Actions
            Column {
                width: parent.width
                spacing: 14

                Row {
                    spacing: 8
                    Rectangle {
                        width: 3
                        height: 18
                        color: "#a855f7"
                        radius: 1.5
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: "NEXA QUICK ACTIONS"
                        font.pixelSize: 13
                        font.bold: true
                        font.family: "Segoe UI, Inter, sans-serif"
                        color: "#c084fc"
                    }
                }

                Grid {
                    width: parent.width
                    columns: parent.width > 700 ? 3 : (parent.width > 480 ? 2 : 1)
                    spacing: 14

                    Repeater {
                        model: [
                            { name: "Screenshot", action: "screenshot", desc: "Capture desktop display", icon: "📸" },
                            { name: "Camera Vision", action: "camera", desc: "Vision AI camera scan", icon: "📷" },
                            { name: "Volume Up", action: "volume_up", desc: "Increase audio (+5%)", icon: "🔊" },
                            { name: "Volume Down", action: "volume_down", desc: "Decrease audio (-5%)", icon: "🔉" },
                            { name: "Mute Microphone", action: "mute_mic", desc: "Toggle audio capture", icon: "🎙️" },
                            { name: "System Telemetry", action: "system_info", desc: "CPU, RAM & Battery", icon: "⚡" }
                        ]

                        Rectangle {
                            width: (mainCol.width - (parent.columns - 1) * 14) / parent.columns
                            height: 84
                            radius: 12
                            color: actMa.containsMouse ? "#191538" : "#0f0f24"
                            opacity: 0.90
                            border.color: actMa.containsMouse ? "#c084fc" : "#2a1e4a"
                            border.width: 1.2

                            Behavior on border.color { ColorAnimation { duration: 150 } }
                            Behavior on color { ColorAnimation { duration: 150 } }

                            Row {
                                anchors.fill: parent
                                anchors.margins: 12
                                spacing: 12

                                Rectangle {
                                    width: 42
                                    height: 42
                                    radius: 10
                                    color: "#1f183d"
                                    border.color: "#3b2b6e"
                                    border.width: 1
                                    anchors.verticalCenter: parent.verticalCenter

                                    Text {
                                        text: modelData.icon
                                        font.pixelSize: 18
                                        anchors.centerIn: parent
                                    }
                                }

                                Column {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: parent.width - 54
                                    spacing: 3

                                    Text {
                                        text: modelData.name
                                        font.pixelSize: 13
                                        font.bold: true
                                        font.family: "Segoe UI, Inter, sans-serif"
                                        color: "#f8fafc"
                                    }

                                    Text {
                                        text: modelData.desc
                                        font.pixelSize: 11
                                        font.family: "Segoe UI, Inter, sans-serif"
                                        color: "#a855f7"
                                        elide: Text.ElideRight
                                        width: parent.width
                                    }
                                }
                            }

                            MouseArea {
                                id: actMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (controller) {
                                        controller.runAction(modelData.action)
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // Status Bar
            Rectangle {
                width: parent.width
                height: 38
                radius: 8
                color: "#0a1322"
                border.color: "#182c47"
                border.width: 1
                visible: controller && controller.lastActionStatus && controller.lastActionStatus.length > 0

                Row {
                    anchors.centerIn: parent
                    spacing: 8
                    Text {
                        text: "●"
                        font.pixelSize: 10
                        color: "#00b4ff"
                    }
                    Text {
                        text: controller ? controller.lastActionStatus : ""
                        font.pixelSize: 12
                        font.family: "Segoe UI, Inter, sans-serif"
                        color: "#cbd5e1"
                    }
                }
            }
        }
    }
}
