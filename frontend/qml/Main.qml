import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Window 2.15

Window {
    id: appWindow
    width: Math.min(1536, Screen.desktopAvailableWidth)
    height: Math.min(1024, Screen.desktopAvailableHeight)
    minimumWidth: Math.min(1200, Screen.desktopAvailableWidth)
    minimumHeight: Math.min(800, Screen.desktopAvailableHeight)
    visible: true
    title: "NEXA Voice Assistant"
    color: "#000000"
    flags: Qt.FramelessWindowHint | Qt.Window

    // Background Image (Earth Horizon, Starfield, Central Glowing Orb)
    Image {
        id: bgImage
        anchors.fill: parent
        source: "../assets/background.png"
        fillMode: Image.PreserveAspectCrop
        smooth: true
    }

    // Draggable Top Area for frameless window movement
    MouseArea {
        id: dragArea
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 60
        property point clickPos: "0,0"
        onPressed: {
            clickPos = Qt.point(mouse.x, mouse.y)
        }
        onPositionChanged: {
            if (mouse.buttons === Qt.LeftButton) {
                var delta = Qt.point(mouse.x - clickPos.x, mouse.y - clickPos.y)
                appWindow.x += delta.x
                appWindow.y += delta.y
            }
        }
    }

    // 1. Top System Bar (Brand text, Battery, Wi-Fi, Volume, Clock, Window controls)
    TopSystemBar {
        id: topBar
    }

    // 2. Left Navigation Rail (Home active glow, Chat, Grid, Settings)
    LeftNavRail {
        id: leftNav
    }

    // 3. Right Conversation Panel (Message bubbles, timestamps, avatars)
    ChatPanel {
        id: chatPanel
    }

    // 4. Center Voice Interaction Section (NEXA brand, Listening..., Waveform, Mic controls)
    CenterVoiceArea {
        id: centerVoice
        anchors.left: leftNav.right
        anchors.right: chatPanel.left
        anchors.top: topBar.bottom
        anchors.bottom: parent.bottom
    }
}
