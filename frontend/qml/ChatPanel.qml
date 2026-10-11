import QtQuick 2.15
import QtQuick.Controls 2.15

Item {
    id: root
    width: 454
    anchors.right: parent.right
    anchors.rightMargin: 30
    anchors.top: parent.top
    anchors.topMargin: 165
    anchors.bottom: parent.bottom
    anchors.bottomMargin: 40

    ListView {
        id: msgList
        anchors.fill: parent
        spacing: 28
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
                    width: isUser ? 28 : 38
                    height: isUser ? 28 : 38
                    anchors.top: parent.top
                    anchors.topMargin: isUser ? 4 : 0

                    // Assistant Avatar: glowing blue orb
                    Image {
                        visible: !isUser
                        anchors.fill: parent
                        source: "../assets/assistant_avatar.png"
                        fillMode: Image.PreserveAspectFit
                        smooth: true
                    }

                    // User Avatar: circle with silhouette
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
                    width: isUser ? 265 : (index === 1 ? 265 : 388)
                    height: contentCol.height + 26
                    radius: 16
                    color: isUser ? "#0c1524" : "#081324"
                    opacity: 0.85
                    border.color: isUser ? "#1e2c42" : "#0f2d4e"
                    border.width: 1.2

                    Column {
                        id: contentCol
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.topMargin: 12
                        anchors.leftMargin: 16
                        anchors.rightMargin: 16
                        spacing: 6

                        Text {
                            id: msgText
                            width: parent.width
                            text: modelData.text
                            font.pixelSize: 14
                            font.family: "Segoe UI, Nirmala UI, Inter, sans-serif"
                            color: "#f8fafc"
                            wrapMode: Text.Wrap
                            lineHeight: 1.3
                        }

                        Text {
                            text: modelData.time
                            font.pixelSize: 11
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
}
