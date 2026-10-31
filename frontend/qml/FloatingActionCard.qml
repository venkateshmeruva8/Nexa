import QtQuick 2.15
import QtQuick.Controls 2.15

Item {
    id: cardRoot
    width: 350
    height: cardBg.height
    opacity: 0.0
    scale: 0.92

    // Properties passed from modelData
    property string cardId: modelData.id || ""
    property string cardType: modelData.type || "SYSTEM"
    property string cardTitle: modelData.title || "Action"
    property string cardSubtitle: modelData.subtitle || ""
    property string cardStatus: modelData.status || "success"
    property string cardDetails: modelData.details || ""
    property string cardIcon: modelData.icon || ""

    // Entrance Animation
    Component.onCompleted: {
        entranceAnim.start()
    }

    ParallelAnimation {
        id: entranceAnim
        NumberAnimation {
            target: cardRoot
            property: "opacity"
            to: 1.0
            duration: 260
            easing.type: Easing.OutCubic
        }
        NumberAnimation {
            target: cardRoot
            property: "scale"
            to: 1.0
            duration: 260
            easing.type: Easing.OutBack
        }
    }

    // Dismiss Animation
    SequentialAnimation {
        id: dismissAnim
        ParallelAnimation {
            NumberAnimation {
                target: cardRoot
                property: "opacity"
                to: 0.0
                duration: 200
                easing.type: Easing.InQuad
            }
            NumberAnimation {
                target: cardRoot
                property: "scale"
                to: 0.85
                duration: 200
                easing.type: Easing.InQuad
            }
        }
        ScriptAction {
            script: {
                if (controller && cardId) {
                    controller.dismissCard(cardId)
                }
            }
        }
    }

    // Main Card Surface
    Rectangle {
        id: cardBg
        width: parent.width
        height: contentCol.height + 24
        radius: 14
        color: "#081324"
        opacity: 0.92
        border.color: {
            if (cardStatus === "loading" || cardStatus === "in_progress") return "#00b4ff"
            if (cardStatus === "failed") return "#ef4444"
            if (cardStatus === "staged" || cardStatus === "pending") return "#f59e0b"
            return "#0284c7"
        }
        border.width: 1.2

        // Left Category Color Strip
        Rectangle {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: 4
            radius: 2
            color: {
                if (cardType === "FILE") return "#38bdf8"
                if (cardType === "SEARCH") return "#818cf8"
                if (cardType === "APP") return "#34d399"
                if (cardType === "REMINDER") return "#fbbf24"
                if (cardType === "EMAIL") return "#a855f7"
                return "#00b4ff"
            }
        }

        // Inner Card Content
        Column {
            id: contentCol
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 16
            anchors.rightMargin: 12
            anchors.topMargin: 12
            spacing: 8

            // Top Header: Category Badge, Status Pill, Close Button
            Row {
                width: parent.width
                spacing: 8

                // Category Badge
                Rectangle {
                    height: 20
                    width: catText.width + 12
                    radius: 4
                    color: {
                        if (cardType === "FILE") return "#0a2540"
                        if (cardType === "SEARCH") return "#1e1b4b"
                        if (cardType === "APP") return "#064e3b"
                        if (cardType === "REMINDER") return "#451a03"
                        if (cardType === "EMAIL") return "#2e1065"
                        return "#0c4a6e"
                    }
                    border.color: {
                        if (cardType === "FILE") return "#0284c7"
                        if (cardType === "SEARCH") return "#6366f1"
                        if (cardType === "APP") return "#10b981"
                        if (cardType === "REMINDER") return "#f59e0b"
                        if (cardType === "EMAIL") return "#9333ea"
                        return "#0ea5e9"
                    }
                    border.width: 0.8
                    anchors.verticalCenter: parent.verticalCenter

                    Text {
                        id: catText
                        text: cardType
                        font.pixelSize: 9
                        font.bold: true
                        font.family: "Segoe UI, Inter, sans-serif"
                        color: "#f8fafc"
                        anchors.centerIn: parent
                    }
                }

                // Status Pill
                Rectangle {
                    height: 20
                    width: statusText.width + (spinnerCanvas.visible ? 24 : 14)
                    radius: 10
                    color: {
                        if (cardStatus === "loading" || cardStatus === "in_progress") return "#0c2847"
                        if (cardStatus === "failed") return "#450a0a"
                        if (cardStatus === "staged" || cardStatus === "pending") return "#451a03"
                        return "#064e3b"
                    }
                    border.color: {
                        if (cardStatus === "loading" || cardStatus === "in_progress") return "#00b4ff"
                        if (cardStatus === "failed") return "#ef4444"
                        if (cardStatus === "staged" || cardStatus === "pending") return "#f59e0b"
                        return "#10b981"
                    }
                    border.width: 0.8
                    anchors.verticalCenter: parent.verticalCenter

                    Row {
                        anchors.centerIn: parent
                        spacing: 4

                        // Spinner Canvas for Loading State
                        Canvas {
                            id: spinnerCanvas
                            width: 10
                            height: 10
                            visible: cardStatus === "loading" || cardStatus === "in_progress"
                            anchors.verticalCenter: parent.verticalCenter

                            property real angle: 0.0

                            NumberAnimation on angle {
                                from: 0.0
                                to: 360.0
                                duration: 800
                                loops: Animation.Infinite
                                running: spinnerCanvas.visible
                            }

                            onAngleChanged: requestPaint()

                            onPaint: {
                                var ctx = getContext("2d")
                                ctx.clearRect(0, 0, width, height)
                                ctx.strokeStyle = "#00b4ff"
                                ctx.lineWidth = 1.8
                                ctx.beginPath()
                                var rad = angle * Math.PI / 180
                                ctx.arc(width / 2, height / 2, 3.8, rad, rad + 1.2 * Math.PI)
                                ctx.stroke()
                            }
                        }

                        Text {
                            id: statusText
                            text: {
                                if (cardStatus === "loading" || cardStatus === "in_progress") return "ACTIVE"
                                if (cardStatus === "staged") return "STAGED"
                                if (cardStatus === "pending") return "VERIFY"
                                if (cardStatus === "failed") return "FAILED"
                                if (cardStatus === "cancelled") return "CANCELLED"
                                return "CONFIRMED"
                            }
                            font.pixelSize: 9
                            font.bold: true
                            font.family: "Segoe UI, Inter, sans-serif"
                            color: {
                                if (cardStatus === "loading" || cardStatus === "in_progress") return "#38bdf8"
                                if (cardStatus === "failed") return "#f87171"
                                if (cardStatus === "staged" || cardStatus === "pending") return "#fbbf24"
                                return "#34d399"
                            }
                        }
                    }
                }

                Item {
                    // Spacer
                    width: Math.max(10, parent.width - catText.width - statusText.width - 70)
                    height: 1
                }

                // Close Button
                Rectangle {
                    width: 22
                    height: 22
                    radius: 11
                    color: closeMa.containsMouse ? "#1e293b" : "transparent"
                    anchors.verticalCenter: parent.verticalCenter

                    Text {
                        text: "✕"
                        font.pixelSize: 11
                        font.family: "Segoe UI, sans-serif"
                        color: closeMa.containsMouse ? "#ffffff" : "#94a3b8"
                        anchors.centerIn: parent
                    }

                    MouseArea {
                        id: closeMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: dismissAnim.start()
                    }
                }
            }

            // Title & Subtitle Row
            Row {
                width: parent.width - 10
                spacing: 10

                // Stylized Category Icon
                Canvas {
                    id: iconCanvas
                    width: 28
                    height: 28
                    anchors.verticalCenter: parent.verticalCenter

                    onPaint: {
                        var ctx = getContext("2d")
                        ctx.clearRect(0, 0, width, height)
                        ctx.lineWidth = 1.6
                        ctx.lineCap = "round"
                        ctx.lineJoin = "round"
                        ctx.strokeStyle = "#38bdf8"

                        if (cardType === "FILE") {
                            // Folder icon
                            ctx.beginPath()
                            ctx.moveTo(3, 8)
                            ctx.lineTo(10, 8)
                            ctx.lineTo(13, 11)
                            ctx.lineTo(25, 11)
                            ctx.lineTo(25, 22)
                            ctx.lineTo(3, 22)
                            ctx.closePath()
                            ctx.stroke()
                        } else if (cardType === "SEARCH") {
                            // Magnifying glass
                            ctx.beginPath()
                            ctx.arc(11, 11, 6, 0, 2 * Math.PI)
                            ctx.stroke()
                            ctx.beginPath()
                            ctx.moveTo(15.5, 15.5)
                            ctx.lineTo(23, 23)
                            ctx.stroke()
                        } else if (cardType === "APP") {
                            // Window / Application launcher
                            ctx.strokeRect(4, 5, 20, 17)
                            ctx.beginPath()
                            ctx.moveTo(4, 10)
                            ctx.lineTo(24, 10)
                            ctx.stroke()
                        } else if (cardType === "REMINDER") {
                            // Bell icon
                            ctx.beginPath()
                            ctx.arc(14, 10, 5, Math.PI, 0, false)
                            ctx.lineTo(21, 18)
                            ctx.lineTo(7, 18)
                            ctx.closePath()
                            ctx.stroke()
                            ctx.beginPath()
                            ctx.arc(14, 21, 2, 0, Math.PI, false)
                            ctx.stroke()
                        } else if (cardType === "EMAIL") {
                            // Envelope
                            ctx.strokeRect(3, 6, 22, 16)
                            ctx.beginPath()
                            ctx.moveTo(3, 6)
                            ctx.lineTo(14, 14)
                            ctx.lineTo(25, 6)
                            ctx.stroke()
                        } else {
                            // System sliders / gear
                            ctx.beginPath()
                            ctx.arc(14, 14, 6, 0, 2 * Math.PI)
                            ctx.stroke()
                        }
                    }
                }

                // Text Information
                Column {
                    width: parent.width - 38
                    spacing: 3

                    Text {
                        text: cardTitle
                        font.pixelSize: 13
                        font.bold: true
                        font.family: "Segoe UI, Inter, sans-serif"
                        color: "#f8fafc"
                        elide: Text.ElideRight
                        width: parent.width
                    }

                    Text {
                        text: cardSubtitle
                        font.pixelSize: 12
                        font.family: "Segoe UI, Inter, sans-serif"
                        color: "#94a3b8"
                        elide: Text.ElideRight
                        width: parent.width
                        visible: cardSubtitle.length > 0
                    }

                    Text {
                        text: cardDetails
                        font.pixelSize: 11
                        font.family: "Segoe UI, Inter, sans-serif"
                        color: "#64748b"
                        wrapMode: Text.Wrap
                        width: parent.width
                        visible: cardDetails.length > 0
                    }
                }
            }
        }
    }
}
