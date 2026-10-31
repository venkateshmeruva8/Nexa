import QtQuick 2.15
import QtQuick.Controls 2.15

Item {
    id: root
    width: controller && controller.activeNav === 1 ? Math.min(840, parent.width - 120) : 454
    anchors.right: controller && controller.activeNav === 1 ? undefined : parent.right
    anchors.horizontalCenter: controller && controller.activeNav === 1 ? parent.horizontalCenter : undefined
    anchors.rightMargin: 30
    anchors.top: parent.top
    anchors.topMargin: 24
    anchors.bottom: parent.bottom
    anchors.bottomMargin: 24

    Behavior on width { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
    Behavior on anchors.topMargin { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }

    ListView {
        id: msgList
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: inputBar.top
        anchors.bottomMargin: 14
        spacing: 24
        clip: true
        model: controller ? controller.messages : []

        onCountChanged: {
            Qt.callLater(function() {
                msgList.positionViewAtEnd();
            });
        }

        Connections {
            target: controller
            function onMessagesChanged() {
                Qt.callLater(function() {
                    msgList.positionViewAtEnd();
                });
            }
        }

        delegate: Item {
            id: delegateRoot
            width: msgList.width
            height: bubbleRect.height

            property bool isUser: modelData.role === "user"

            Row {
                id: msgRow
                anchors.right: isUser ? parent.right : undefined
                anchors.left: isUser ? undefined : parent.left
                spacing: 12
                layoutDirection: isUser ? Qt.RightToLeft : Qt.LeftToRight

                // Avatar
                Item {
                    width: isUser ? 28 : 36
                    height: isUser ? 28 : 36
                    anchors.top: parent.top
                    anchors.topMargin: isUser ? 4 : 0

                    // Assistant Avatar
                    Image {
                        visible: !isUser
                        anchors.fill: parent
                        source: "../assets/assistant_avatar.png"
                        fillMode: Image.PreserveAspectFit
                        smooth: true
                    }

                    // User Avatar
                    Rectangle {
                        visible: isUser
                        anchors.fill: parent
                        radius: width / 2
                        color: "#0a192f"
                        border.color: "#1e293b"
                        border.width: 1

                        Image {
                            anchors.fill: parent
                            source: "../assets/user_avatar.png"
                            fillMode: Image.PreserveAspectFit
                            smooth: true
                        }
                    }
                }

                // Message Bubble
                Rectangle {
                    id: bubbleRect
                    width: Math.min(msgList.width - 60, Math.max(140, isUser ? 280 : 420))
                    height: contentCol.height + 24
                    radius: 14
                    color: isUser ? "#0c1524" : "#081324"
                    opacity: 0.88
                    border.color: isUser ? "#1e2c42" : "#0f2d4e"
                    border.width: 1.2

                    Column {
                        id: contentCol
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.topMargin: 10
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14
                        spacing: 6

                        Text {
                            id: msgText
                            width: parent.width
                            text: modelData.text
                            font.pixelSize: 13
                            font.family: "Segoe UI, Nirmala UI, Inter, sans-serif"
                            color: "#f8fafc"
                            wrapMode: Text.Wrap
                            lineHeight: 1.3
                        }

                        Text {
                            text: modelData.time || ""
                            font.pixelSize: 10
                            font.family: "Segoe UI, Nirmala UI, Inter, sans-serif"
                            color: "#64748b"
                            anchors.right: isUser ? parent.right : undefined
                            anchors.left: isUser ? undefined : parent.left
                        }
                    }
                }
            }
        }
    }

    // Input Bar
    Rectangle {
        id: inputBar
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 48
        radius: 12
        color: "#081324"
        opacity: 0.92
        border.color: chatInput.activeFocus ? "#00b4ff" : "#1a2c47"
        border.width: 1.2

        Row {
            anchors.fill: parent
            anchors.margins: 6
            spacing: 8

            TextField {
                id: chatInput
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - 44
                height: 36
                placeholderText: "Type a message or command to NEXA..."
                placeholderTextColor: "#64748b"
                color: "#f8fafc"
                font.pixelSize: 13
                font.family: "Segoe UI, Inter, sans-serif"
                background: Rectangle { color: "transparent" }
                onAccepted: {
                    if (text.trim().length > 0 && controller) {
                        controller.sendMessage(text.trim())
                        text = ""
                    }
                }
            }

            Rectangle {
                width: 36
                height: 36
                radius: 8
                anchors.verticalCenter: parent.verticalCenter
                color: sendMa.containsMouse ? "#00b4ff" : "#0284c7"

                Text {
                    text: "➤"
                    font.pixelSize: 14
                    color: "#ffffff"
                    anchors.centerIn: parent
                }

                MouseArea {
                    id: sendMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        if (chatInput.text.trim().length > 0 && controller) {
                            controller.sendMessage(chatInput.text.trim())
                            chatInput.text = ""
                        }
                    }
                }
            }
        }
    }
}
