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
        z: 50
    }

    // 2. Left Navigation Rail (Home, Chat, Apps, Settings)
    LeftNavRail {
        id: leftNav
        z: 50
    }

    // Main Interactive Content Area
    Item {
        id: contentArea
        anchors.left: leftNav.right
        anchors.right: parent.right
        anchors.top: topBar.bottom
        anchors.bottom: parent.bottom

        // Screen 0: Home (Center Orbital Assistant + Docked Right ChatPanel)
        Item {
            id: homeView
            anchors.fill: parent
            opacity: controller && controller.activeNav === 0 ? 1.0 : 0.0
            visible: opacity > 0.0

            Behavior on opacity {
                NumberAnimation { duration: 180; easing.type: Easing.InOutQuad }
            }

            CenterVoiceArea {
                id: centerVoice
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.rightMargin: chatPanel.width + 30
                anchors.top: parent.top
                anchors.bottom: parent.bottom
            }
        }

        // Screen 0 & 1 Shared ChatPanel (Docked on Right on Home, Expanded on Chat Screen)
        ChatPanel {
            id: chatPanel
            visible: controller && (controller.activeNav === 0 || controller.activeNav === 1)
            opacity: visible ? 1.0 : 0.0
            z: 10

            Behavior on opacity {
                NumberAnimation { duration: 180; easing.type: Easing.InOutQuad }
            }
        }

        // Screen 2: Apps View (Desktop App Launchers & Quick Tools)
        AppsView {
            id: appsView
            anchors.fill: parent
            opacity: controller && controller.activeNav === 2 ? 1.0 : 0.0
            visible: opacity > 0.0
            z: 10

            Behavior on opacity {
                NumberAnimation { duration: 180; easing.type: Easing.InOutQuad }
            }
        }

        // Screen 3: Settings View (Audio, Volume, Telemetry, Maintenance)
        SettingsView {
            id: settingsView
            anchors.fill: parent
            opacity: controller && controller.activeNav === 3 ? 1.0 : 0.0
            visible: opacity > 0.0
            z: 10

            Behavior on opacity {
                NumberAnimation { duration: 180; easing.type: Easing.InOutQuad }
            }
        }

        // Context-Aware Floating Action Cards Overlay (Top-Right, Non-Intrusive)
        FloatingCardContainer {
            id: floatingCards
            z: 100
        }
    }
}
