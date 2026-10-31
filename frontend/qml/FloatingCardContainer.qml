import QtQuick 2.15
import QtQuick.Controls 2.15

Item {
    id: containerRoot
    width: 350
    anchors.right: parent.right
    anchors.rightMargin: 24
    anchors.top: parent.top
    anchors.topMargin: 74
    anchors.bottom: parent.bottom
    anchors.bottomMargin: 24
    z: 100

    ListView {
        id: cardList
        anchors.fill: parent
        spacing: 12
        clip: false
        interactive: false
        model: controller ? controller.actionCards : []

        delegate: FloatingActionCard {
            id: cardDelegate
        }

        // Smooth animations on item changes
        add: Transition {
            NumberAnimation {
                property: "opacity"
                from: 0.0
                to: 1.0
                duration: 260
                easing.type: Easing.OutCubic
            }
            NumberAnimation {
                property: "y"
                from: -20
                duration: 260
                easing.type: Easing.OutCubic
            }
        }

        displaced: Transition {
            NumberAnimation {
                properties: "y,opacity"
                duration: 220
                easing.type: Easing.OutCubic
            }
        }
    }
}
